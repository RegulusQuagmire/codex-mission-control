"""Personal model ceilings, separate from capabilities and security approvals."""
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
from copy import deepcopy

from .routing import RoutingBlocked

EFFORT_ORDER = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra')
OWNER_PROFILE = {
    'gpt-6-astra': {'maxEffort': 'low', 'automaticEnabled': True},
    'gpt-6.1-sol': {'maxEffort': 'medium', 'automaticEnabled': True},
    'gpt-6-luna': {'maxEffort': 'high', 'automaticEnabled': True},
}
_PROVIDER = ContextVar('model_policy_provider', default=None)
AUTOMATIC = ContextVar('automatic_model_submission', default=False)


class PolicyBlocked(RoutingBlocked):
    """Known pre-send rejection: turn/start has not been written."""


def validate_policy(value):
    if not isinstance(value, dict) or len(value) > 1000:
        raise ValueError('Model policy must be a bounded map of exact model IDs')
    for model, rule in value.items():
        if (not isinstance(model, str) or not model.strip() or len(model) > 200
                or not isinstance(rule, dict) or set(rule) != {'maxEffort', 'automaticEnabled'}
                or rule['maxEffort'] not in EFFORT_ORDER
                or type(rule['automaticEnabled']) is not bool):
            raise ValueError('Invalid model policy: exact ID, supported ceiling and boolean required')
    return deepcopy(value)


def current_policy():
    provider = _PROVIDER.get()
    if provider is not None:
        return validate_policy(provider())
    from .storage import ACTIVE_STORE
    store = ACTIVE_STORE.get()
    if store is not None and store.exists('gui-preferences'):
        return validate_policy(store.load('gui-preferences').get('modelPolicies', {}))
    return {}


@contextmanager
def policy_context(provider):
    token = _PROVIDER.set(provider)
    try:
        yield
    finally:
        _PROVIDER.reset(token)


@contextmanager
def submission_mode(automatic):
    token = AUTOMATIC.set(automatic)
    try:
        yield
    finally:
        AUTOMATIC.reset(token)


def allowed_efforts(model, efforts, *, automatic, policy=None):
    policy = current_policy() if policy is None else policy
    rule = policy.get(model)
    if automatic and rule is not None and not rule['automaticEnabled']:
        return []
    ceiling = EFFORT_ORDER.index(rule['maxEffort']) if rule else len(EFFORT_ORDER) - 1
    return [e for e in EFFORT_ORDER[:ceiling + 1] if e in efforts
            and (not automatic or e != 'ultra')]


def validate_configuration(models, model, effort, *, automatic=False):
    # A duplicate identifier is ambiguous; never infer by display name or suffix.
    entries = [entry for entry in models if entry.get('model') == model]
    if len(entries) != 1:
        raise PolicyBlocked('Selected model missing or ambiguous in current catalog')
    entry = entries[0]
    efforts = {option.get('reasoningEffort') for option in entry.get('supportedReasoningEfforts', [])}
    if (entry.get('hidden') or ('inputModalities' in entry and 'text' not in entry['inputModalities'])
            or effort not in allowed_efforts(model, efforts, automatic=automatic)):
        raise PolicyBlocked('Selected model/effort forbidden by current policy or catalog')


@contextmanager
def submission_guard(models, model, effort, *, automatic, extra_check=None):
    """Serialize the final policy read and synchronous write with preference saves."""
    from .storage import ACTIVE_STORE
    from .state import state_lock, StateError
    with ExitStack() as stack:
        store = ACTIVE_STORE.get()
        if store is not None:
            try:stack.enter_context(state_lock(store.path))
            except StateError as error:
                raise PolicyBlocked('Model policy is being edited; no turn submitted') from error
        validate_configuration(models, model, effort, automatic=automatic)
        if extra_check is not None:
            extra_check()
        yield
