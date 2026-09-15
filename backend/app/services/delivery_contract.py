"""S9 public delivery metadata. No authority is synthesized for legacy arrays."""
from datetime import datetime, timedelta, timezone
import uuid

MAX_SEQUENCE = 9_007_199_254_740_991  # exact across SQL, Swift and JSON consumers


def metadata(stored, request_id, result, *, now=None):
    now = now or datetime.now(timezone.utc)
    sequence = stored.get('publication_sequence')
    published = stored.get('created_at')
    expiry = stored.get('expires_at')
    if type(sequence) is not int or not 1 <= sequence <= MAX_SEQUENCE:
        raise ValueError('delivery_publication_missing')
    for value in (published, expiry, now):
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise ValueError('delivery_timestamp_invalid')
    if not published <= now < expiry or expiry - published > timedelta(minutes=15):
        raise ValueError('delivery_expired')
    identity = {key: result.get(key) for key in ('reader_generation', 'reader_revision')}
    if any(type(value) is not int or not 1 <= value <= MAX_SEQUENCE for value in identity.values()):
        raise ValueError('delivery_reader_invalid')
    return {'version': 1, 'edition_id': str(uuid.UUID(request_id)),
            'sequence': sequence, 'published_at': published.isoformat(),
            'validated_at': now.isoformat(), 'valid_until': expiry.isoformat(), **identity}


def negotiated(result, version):
    """Missing legacy metadata stays missing; old enum clients retain old semantics."""
    if version != '1':
        if not any(key in result for key in ('delivery', 'reason', 'retry_after_seconds')):
            return result
        result = dict(result)
        result.pop('delivery', None)
        result.pop('reason', None)
        result.pop('retry_after_seconds', None)
        return result
    result = dict(result)
    status = result.get('status')
    if status in {'building', 'unavailable', 'needs_build', 'needs_reader_review'}:
        result.setdefault('reason', {'building': 'build_in_progress',
            'unavailable': 'temporarily_unavailable', 'needs_build': 'edition_missing_or_stale',
            'needs_reader_review': 'reader_review_required'}[status])
        if status in {'building', 'unavailable'}:
            result.setdefault('retry_after_seconds', 5)
    return result


def native_lease(article, *, policy, now=None):
    """Explicit policy only. Native display rights alone never imply offline rights."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError('delivery_timestamp_invalid')
    result = {**article, 'presentation': dict(article.get('presentation') or {})}
    presentation = result['presentation']
    presentation['validated_at'] = now.isoformat()
    presentation['offline_valid_until'] = None
    seconds = policy.get('offline_cache_seconds')
    provenance = presentation.get('provenance') or {}
    if (presentation.get('mode') == 'native_full_text' and presentation.get('body')
            and type(seconds) is int and 0 < seconds <= 86400
            and policy.get('display_policy') == 'native_full_text'
            and policy.get('version') == provenance.get('policy_version')):
        presentation['offline_valid_until'] = (now + timedelta(seconds=seconds)).isoformat()
    return result
