"""Polymetis: decides per session which skills and tools a Hermes model gets, and logs what it decided.

Settings live in plugins.entries.polymetis.settings in the profile's config.yaml. With the defaults,
``apply`` empty and no ablation, Polymetis only decides and logs and every request goes out as Hermes
built it.
"""

import sys
import types

from . import cli, hooks

ROUTER_HOOKS = "polytropos_router_hooks"  # the request hook point that polytropos-router offers


def _router_hooks() -> dict:
    store = sys.modules.setdefault(ROUTER_HOOKS, types.ModuleType(ROUTER_HOOKS))
    return store.__dict__.setdefault("local_request", {})


def _data_dir(ctx):
    try:  # the profile's plugin-data folder, on Hermes versions that have it
        state = ctx.state
        state.data_dir
    except Exception:
        return None
    return lambda: state.data_dir


def register(ctx) -> None:
    hooks.configure(ctx.get_config, _data_dir(ctx))
    ctx.register_cli_command("polymetis", "Polymetis skill router: report", cli.setup_parser, cli.handle)
    ctx.register_hook("pre_llm_call", hooks.on_pre_llm_call)
    ctx.register_hook("pre_api_request", hooks.on_pre_api_request)
    ctx.register_hook("post_api_request", hooks.on_post_api_request)
    ctx.register_hook("post_tool_call", hooks.on_post_tool_call)
    ctx.register_hook("on_session_end", hooks.on_session_end)
    ctx.register_hook("post_compaction", hooks.on_post_compaction)
    ctx.register_hook("api_request_error", hooks.on_api_request_error)
    ctx.register_hook("on_session_finalize", hooks.on_session_finalize)  # Hermes ends its processes past atexit
    ctx.register_hook("subagent_stop", hooks.on_subagent_stop)
    # While any llm_request middleware is registered, Hermes deep-copies every request several times, so
    # Polymetis adds its own only while an ablation runs; one set later starts when Hermes loads the plugin again
    hooks.ablation_ready = hasattr(ctx, "register_middleware") and hooks._refresh_settings().ablation_active()
    if hooks.ablation_ready:
        ctx.register_middleware("llm_request", hooks.on_llm_request)
        ctx.register_hook("pre_tool_call", hooks.on_pre_tool_call)
    # keyed by module, as Hermes loads the plugin once per profile under its own name; a reload replaces it
    shape_local = hooks.shape_local
    _router_hooks()[__name__] = shape_local
    if hasattr(ctx, "on_unload"):  # leaves a hook that a reload put there since
        ctx.on_unload(lambda: _router_hooks().pop(__name__) if _router_hooks().get(__name__) is shape_local else None)
