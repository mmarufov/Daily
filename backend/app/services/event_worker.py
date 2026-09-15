"""Independent S4 worker: python -m app.services.event_worker.

Disabled by default. Each database operation gets a short separate checkout;
no connection or transaction survives across provider I/O. Database controls,
recipe approvals, generation fences and the reservation ledger remain authority.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import signal

from . import event_repository as repo
from .event_provider import OpenAIEventProvider, ProviderFailure

logger = logging.getLogger(__name__)


class EventWorker:
    def __init__(self, pool, provider, *, concurrency=4, repository=repo):
        if type(concurrency) is not int or not 1 <= concurrency <= 16:
            raise ValueError("concurrency must be an integer from 1 to 16")
        self.pool, self.provider, self.repository = pool, provider, repository
        self.concurrency = concurrency
        self.stop = asyncio.Event()

    async def db(self, function, *args, **kwargs):
        def operation():
            with self.pool.connection() as connection:
                return function(connection, *args, **kwargs)
        operation_task = asyncio.create_task(asyncio.to_thread(operation))
        try:
            return await asyncio.shield(operation_task)
        except asyncio.CancelledError:
            # A thread cannot be cancelled. Wait for the bounded SQL operation
            # to release its checkout before shutdown closes the pool. A spend
            # reservation committed during cancellation remains conservatively held.
            while not operation_task.done():
                try:
                    await asyncio.shield(operation_task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if operation_task.done() and not operation_task.cancelled():
                operation_task.exception()
            raise

    async def process(self, job):
        repository = self.repository
        reservation = None
        try:
            stage = job["stage"]
            if stage == "ingest":
                await self.db(repository.ingest, job)
                return
            if stage == "group":
                await self.db(repository.group, job)
                return
            if stage not in ("refine", "assess"):
                await self.db(repository.fail, job, "contract_invalid", retryable=False)
                return
            frozen = await self.db(repository.prepare, job)
            if frozen is None:
                return
            definition = job["definition"].get("refinement_provider" if stage == "refine" else "provider")
            if not isinstance(definition, dict):
                # Missing provider config is not permission to invent a model or
                # publish a routine verdict. A changed config creates a new recipe.
                await self.db(repository.fail, job, "unsupported_refinement" if stage == "refine" else "contract_invalid",
                              retryable=False)
                return
            config = {**definition, "recipe_id": job["recipe_id"]}
            if stage == "refine":
                evidence, bundle = await self.db(repository.refinement_inputs, job, frozen)
                prepared = self.provider.prepare_refinement(evidence, bundle, config)
            else:
                prepared = self.provider.prepare_request(frozen, config)
            reservation = await self.db(repository.reserve, job, prepared.max_cost_usd, prepared.request_hash)
            if reservation is None:
                await self.db(repository.defer_without_attempt, job, "budget_paused", delay=300)
                return
            # This is the only network step. Every prior checkout has ended.
            outcome = await self.provider.generate_prepared(prepared)
            await self.db(repository.settle, reservation, outcome.usage_usd, outcome.request_id)
            if stage == "refine":
                await self.db(repository.publish_refinement, job, frozen, outcome.payload)
            else:
                await self.db(repository.publish, job, frozen, outcome.payload)
        except asyncio.CancelledError:
            # Do not release unknown charges or renew leases/decisions. Reaper
            # and reservation reconciliation recover this exact attempt.
            raise
        except repository.LeaseLost:
            return
        except repository.StaleInput:
            await self.db(repository.fail, job, "input_changed", retryable=False)
        except ProviderFailure as error:
            if reservation is not None:
                if error.usage_usd is not None:
                    await self.db(repository.settle, reservation, error.usage_usd, error.request_id)
                elif not error.ambiguous:
                    await self.db(repository.settle, reservation, 0, error.request_id)
            attempts = job.get("attempts", 1)
            attempts = attempts if type(attempts) is int and attempts > 0 else 1
            delay = error.retry_after
            if type(delay) not in (int, float) or not math.isfinite(delay):
                delay = 30 * 2 ** min(attempts - 1, 7)
            delay = min(3600, max(1, delay))
            if error.provider_wide:
                await self.db(repository.pause_provider, "provider_failure", delay=delay)
            await self.db(repository.fail, job, "provider_failure", retryable=error.retryable, retry_after=delay)
        except (ValueError, TypeError, KeyError):
            await self.db(repository.fail, job, "contract_invalid", retryable=False)
        except Exception:
            # IDs and failure categories only; never include source, provider or
            # DB exception text (which can embed a frozen private evidence body).
            logger.error("S4 stage failed; job=%s stage=%s", job.get("id"), job.get("stage"))
            await self.db(repository.fail, job, "internal_failure", retryable=True, retry_after=60)

    async def tick(self):
        repository = self.repository
        await self.db(repository.consume_changes, limit=100)
        await self.db(repository.scan, limit=100)
        await self.db(repository.reap)
        jobs = await self.db(repository.claim, limit=self.concurrency)
        # Repository validates/fairly bounds claims. Do not silently slice and
        # leave already-leased excess jobs behind if that contract regresses.
        if len(jobs) > self.concurrency:
            raise ValueError("claim exceeded worker concurrency")
        tasks = [asyncio.create_task(self.process(job)) for job in jobs]
        try:
            await asyncio.gather(*tasks)
        finally:
            # gather does not cancel siblings when one DB failure escapes. Drain
            # all children before another tick or closing the connection pool.
            for task in tasks:
                if not task.done() and not task.cancelling():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        return len(jobs)

    async def run(self):
        await self.db(self.repository.check_schema)
        while not self.stop.is_set():
            tick = asyncio.create_task(self.tick())
            stopped = asyncio.create_task(self.stop.wait())
            try:
                done, _ = await asyncio.wait((tick, stopped), return_when=asyncio.FIRST_COMPLETED)
                if stopped in done:
                    return
                processed = await tick
                delay = 0.25 if processed else 5
            except Exception:
                logger.error("S4 worker database unavailable; retrying")
                delay = 10
            finally:
                for task in (tick, stopped):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(tick, stopped, return_exceptions=True)
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=delay)
            except TimeoutError:
                pass


async def main():
    from dotenv import load_dotenv
    load_dotenv()
    if os.getenv("S4_WORKER_ENABLED", "false").lower() != "true":
        logger.info("S4 worker disabled")
        return
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
    provider = OpenAIEventProvider(os.environ["OPENAI_API_KEY"])
    pool = None
    try:
        pool = ConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=4,
            kwargs={"row_factory": dict_row, "autocommit": True,
                    "options": "-c statement_timeout=30000 -c lock_timeout=5000"})
        worker = EventWorker(pool, provider)
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, worker.stop.set)
        await worker.run()
    finally:
        await provider.aclose()
        if pool is not None:
            pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
