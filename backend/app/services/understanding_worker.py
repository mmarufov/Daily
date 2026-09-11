"""Independent S3 worker: python -m app.services.understanding_worker.

Every database operation is a short transaction on a separate pooled checkout.
No connection survives across an awaited provider request. Disabled by default
in both process configuration and the authoritative database control row.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import signal

from app.services import understanding_repository as repo
from app.services.understanding_provider import OpenAIUnderstandingProvider, ProviderFailure

logger = logging.getLogger(__name__)


class UnderstandingWorker:
    def __init__(self, pool, provider, *, concurrency=4):
        self.pool = pool
        self.provider = provider
        self.concurrency = max(1, min(int(concurrency), 16))
        self.stop = asyncio.Event()
        self.tick_number = 0

    async def db(self, function, *args, **kwargs):
        def operation():
            with self.pool.connection() as conn:
                return function(conn, *args, **kwargs)
        return await asyncio.to_thread(operation)

    async def process(self, job):
        reservation = None
        try:
            bundle = await self.db(repo.prepare, job)
            if bundle is None:
                return
            if job['stage'] == 'cluster':
                from app.services.story_clustering import assign_story
                await self.db(assign_story, job, bundle)
                return
            estimate = self.provider.estimate_usd(stage=job['stage'],bundle=bundle,recipe=job['definition'])
            reservation = await self.db(repo.reserve, job, estimate)
            if reservation is None:
                await self.db(repo.defer_without_attempt, job, 'budget_or_provider_paused', delay=300)
                return
            outcome = await self.provider.generate(stage=job['stage'],bundle=bundle,recipe=job['definition'])
            await self.db(repo.settle, reservation, outcome.usage_usd)
            await self.db(repo.publish, job,bundle,outcome.payload,outcome.usage_usd,outcome.request_id)
        except asyncio.CancelledError:
            # A sent request may already be billed. Reservation remains conservative;
            # lease reaper handles recovery and publication is still token-fenced.
            raise
        except ProviderFailure as exc:
            if reservation is not None:
                if exc.usage_usd is not None:
                    await self.db(repo.settle, reservation, exc.usage_usd)
                elif not exc.ambiguous:
                    await self.db(repo.settle, reservation, 0)
            delay = exc.retry_after or min(3600,30*2**(job['attempts']-1)) * random.uniform(1,1.2)
            await self.db(repo.fail,job,exc.kind,retryable=exc.retryable,retry_after=delay,
                          provider_wide=exc.provider_wide)
        except (ValueError, TypeError, KeyError):
            # Validation errors are explicit outcomes; don't log private payloads.
            await self.db(repo.fail,job,'contract_validation_failed',retryable=False)
        except Exception:
            logger.error('S3 stage failed; job=%s stage=%s',job['id'],job['stage'])
            await self.db(repo.fail,job,'internal_failure',retry_after=60)

    async def tick(self):
        await self.db(repo.reap)
        self.tick_number += 1
        # At least every fourth tick reserves a full slot for backfill. Separate
        # claims prevent the fresh queue monopolizing historic capacity.
        fresh = self.tick_number % 4 != 0
        jobs = await self.db(repo.claim,limit=self.concurrency,fresh=fresh)
        if len(jobs)<self.concurrency:
            jobs += await self.db(repo.claim,limit=self.concurrency-len(jobs),fresh=not fresh)
        await asyncio.gather(*(self.process(job) for job in jobs))
        return len(jobs)

    async def run(self):
        await self.db(repo.check_schema)
        while not self.stop.is_set():
            tick = asyncio.create_task(self.tick())
            stopped = asyncio.create_task(self.stop.wait())
            try:
                done, _ = await asyncio.wait((tick, stopped), return_when=asyncio.FIRST_COMPLETED)
                if stopped in done:
                    # Interrupt in-flight network requests promptly. Their spend
                    # reservations stay charged until actual usage is known.
                    return
                processed = await tick
                delay = 0.25 if processed else 5
            except Exception:
                logger.error('S3 worker database unavailable; retrying')
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
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
    load_dotenv()
    if os.getenv('S3_WORKER_ENABLED','false').lower() != 'true':
        logger.info('S3 worker disabled')
        return
    database_url = os.environ['DATABASE_URL']
    provider = OpenAIUnderstandingProvider(os.environ['OPENAI_API_KEY'])
    pool = ConnectionPool(database_url,min_size=1,max_size=4,
                          kwargs={'row_factory':dict_row,'autocommit':True,
                                  'options':'-c statement_timeout=30000 -c lock_timeout=5000'})
    worker = UnderstandingWorker(pool,provider)
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT,signal.SIGTERM):
        loop.add_signal_handler(signum,worker.stop.set)
    try:
        await worker.run()
    finally:
        await provider.aclose()
        pool.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
