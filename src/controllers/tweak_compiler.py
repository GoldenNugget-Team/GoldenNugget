"""Compile tweak selections into owned restore artifacts before device restore."""
import inspect
import logging
import plistlib
from dataclasses import dataclass, field
from functools import singledispatch
from tempfile import TemporaryDirectory
from typing import Callable, Mapping

from packaging.version import Version

from src.controllers.path_handler import fix_windows_path
from src.devicemanagement.device_capabilities import has_dynamic_island
from src.exceptions.nugget_exception import NuggetException
from src.tweaks.basic_plist_locations import FileLocation
from src.tweaks.candidate_preferences import InstalledAppSuggestionsBlacklist
from src.tweaks.compatibility import hardware_reasons
from src.tweaks.icon_themes.icon_themes_tweak import IconThemesTweak
from src.tweaks.posterboard.device_overrides import PosterKitOverrides
from src.tweaks.posterboard.posterboard_tweak import PosterboardTweak
from src.tweaks.posterboard.template_options.templates_tweak import TemplatesTweak
from src.tweaks.registry import HOME_PREFIX, SPECS_BY_ID, managed_pref_target
from src.tweaks.siri_ai import SiriAITweak
from src.tweaks.status_bar.status_bar_tweak import StatusBarTweak
from src.tweaks.tweak_classes import (
    AdvancedPlistTweak,
    BasicPlistTweak,
    NullifyFileTweak,
    ResearchOnlyTweak,
    ReversibleBooleanPlistTweak,
)
from src.tweaks.tweak_names import TweakID
from src.utils.i18n import QCoreApplication

log = logging.getLogger("GoldenNugget.compiler")


@dataclass(frozen=True)
class CompilationContext:
    store: Mapping
    version: str
    model: str
    templates: list
    force_pb_refresh: bool
    prepare_setup: Callable
    concat_file: Callable
    add_community_files: Callable
    update_label: Callable
    udid: str = ''


@dataclass
class TweakArtifacts:
    files: list = field(default_factory=list)
    temporary_dirs: list = field(default_factory=list)
    uses_domains: bool = False
    community_writes: tuple = field(default_factory=lambda: ({}, {}))

    def close(self):
        for directory in self.temporary_dirs:
            try:
                directory.cleanup()
            except OSError:
                log.exception("Could not remove temporary tweak artifacts")
        self.temporary_dirs.clear()


@dataclass
class _Compilation:
    context: CompilationContext
    artifacts: TweakArtifacts = field(default_factory=TweakArtifacts)
    plists: dict = field(default_factory=dict)
    ownership: dict = field(default_factory=dict)
    raw_files: dict = field(default_factory=dict)


@singledispatch
def compile_one(tweak, tweak_id, state):
    raise TypeError(f"No compiler registered for {type(tweak).__name__}")


@compile_one.register(BasicPlistTweak)
@compile_one.register(AdvancedPlistTweak)
@compile_one.register(ReversibleBooleanPlistTweak)
def _compile_plist(tweak, tweak_id, state):
    state.plists = tweak.apply_tweak(state.plists)
    state.ownership[tweak.file_location] = tweak.owner


@compile_one.register(NullifyFileTweak)
def _compile_nullify(tweak, tweak_id, state):
    tweak.apply_tweak(state.raw_files)
    state.artifacts.uses_domains |= tweak.enabled and tweak.file_location.value.startswith("/var/mobile/")


@compile_one.register(PosterboardTweak)
@compile_one.register(TemplatesTweak)
def _compile_package(tweak, tweak_id, state):
    context = state.context
    directory = TemporaryDirectory()
    state.artifacts.temporary_dirs.append(directory)
    tweak.apply_tweak(files_to_restore=state.artifacts.files,
                      output_dir=fix_windows_path(directory.name),
                      templates=context.templates, version=context.version,
                      force_pb_refresh=context.force_pb_refresh,
                      update_label=context.update_label)
    state.artifacts.uses_domains |= tweak.uses_domains()


@compile_one.register(IconThemesTweak)
def _compile_icons(tweak, tweak_id, state):
    tweak.apply_tweak(files_to_restore=state.artifacts.files,
                      update_label=state.context.update_label)
    state.artifacts.uses_domains |= tweak.uses_domains()


@compile_one.register(StatusBarTweak)
def _compile_status_bar(tweak, tweak_id, state):
    apply = tweak.apply_ios27_tweak if Version(state.context.version) >= Version("27.0") else tweak.apply_classic_tweak
    apply(state.artifacts.files)
    state.artifacts.uses_domains |= tweak.enabled


@compile_one.register(SiriAITweak)
def _compile_siri(tweak, tweak_id, state):
    if not tweak.enabled:
        return
    peer = TweakID.ResetSiriAIOverrides if tweak_id == TweakID.SiriAI else TweakID.SiriAI
    if state.context.store[peer].enabled:
        raise NuggetException("Choose either Siri AI or Reset Siri AI Overrides, not both.")
    tweak.apply_tweak(state.artifacts.files, state.context.version, state.context.model)
    state.artifacts.uses_domains = True


@compile_one.register(PosterKitOverrides)
async def _compile_posterkit(tweak,tweak_id,state):
    if not tweak.enabled or not tweak.value:
        return
    context=state.context
    if not context.store[TweakID.PosterBoard].is_empty() or context.templates:
        raise NuggetException('Apply PosterKit settings separately from wallpaper imports and resets.')
    from src.restore.posterboard_backup import pull_posterboard_container
    directory=TemporaryDirectory()
    state.artifacts.temporary_dirs.append(directory)
    context.update_label(QCoreApplication.tr('Fetching current wallpaper configurations...'))
    await pull_posterboard_container(context.udid,directory.name,update_label=context.update_label)
    state.artifacts.files.extend(tweak.stage(directory.name))
    state.artifacts.uses_domains=True


@compile_one.register(ResearchOnlyTweak)
def _compile_research(tweak,tweak_id,state):
    if tweak.enabled:
        raise NuggetException(tweak.reason)


async def compile_tweaks(context: CompilationContext, hotload, unavailable=()) -> TweakArtifacts:
    state = _Compilation(context)
    store, version, model = context.store, context.version, context.model
    skipped = []
    hidden = hotload.hidden_tweak_names(device_version=version, device_model=model)
    try:
        for tweak_id, tweak in store.items():
            if tweak_id in unavailable:
                continue
            spec = SPECS_BY_ID.get(tweak_id)
            if spec is not None and spec.experimental and (spec.unavailable_reason or hardware_reasons(spec, model)):
                continue
            if tweak_id in (TweakID.Daemons, TweakID.ClearScreenTimeAgentPlist) and not store[TweakID.Daemons].enabled:
                continue
            if tweak_id in (TweakID.SBAlwaysShowSystemApertureInSnapshots, TweakID.HideDICompletely) and not has_dynamic_island(model):
                continue
            if tweak_id.name in hidden or hotload.rule_for(tweak_id, device_version=version, device_model=model) is not None:
                skipped.append(tweak_id)
                continue
            if isinstance(tweak,InstalledAppSuggestionsBlacklist) and tweak.enabled:
                await tweak.prepare_for_device(context.udid)
            result=compile_one(tweak, tweak_id, state)
            if inspect.isawaitable(result):
                await result

        community_plists, community_files = {}, {}
        if TweakID.Templates in store and TweakID.Templates not in skipped:
            community_plists, community_files = store[TweakID.Templates].community_writes(version)
            state.artifacts.uses_domains |= bool(community_plists or community_files)
        state.artifacts.community_writes = dict(community_plists), dict(community_files)
        if skipped:
            context.update_label(QCoreApplication.tr("Skipped HotLoad-flagged tweaks: ") +
                                 ", ".join(sorted(item.name for item in skipped)))
        daemon = store.get(TweakID.Daemons)
        if daemon is not None:
            forced = hotload.disabled_daemon_keys(device_version=version, device_model=model) - daemon.never_enable
            if forced:
                state.plists.setdefault(FileLocation.disabledDaemons, {}).update(dict.fromkeys(forced, True))
                state.ownership[FileLocation.disabledDaemons] = 0

        context.update_label(QCoreApplication.tr("Generating backup..."))
        is_ios27 = Version(version) >= Version("27.0")
        await context.prepare_setup(state.artifacts.files, state.artifacts.uses_domains)
        for location, values in state.plists.items():
            owner = state.ownership.get(location, 501)
            if location.value in community_plists:
                values = {**community_plists.pop(location.value)[0], **values}
            if not values:
                continue
            payload = plistlib.dumps(values)
            context.concat_file(contents=payload, path=location.value,
                                files_to_restore=state.artifacts.files, owner=owner, group=owner)
            mirror = managed_pref_target(location.value) if is_ios27 else None
            if mirror and location != FileLocation.globalPreferences:
                context.concat_file(contents=payload, path=f"{HOME_PREFIX}{mirror}",
                                    files_to_restore=state.artifacts.files, owner=501, group=501)
        home = state.plists.get(FileLocation.globalPreferences, {})
        if FileLocation.globalPreferencesHomeDomain.value in community_plists:
            home = {**community_plists.pop(FileLocation.globalPreferencesHomeDomain.value)[0], **home}
        if home:
            context.concat_file(contents=plistlib.dumps(home), path=FileLocation.globalPreferencesHomeDomain.value,
                                files_to_restore=state.artifacts.files, owner=501, group=501)
        for location, data in state.raw_files.items():
            context.concat_file(contents=data, path=location.value,
                                files_to_restore=state.artifacts.files, owner=501, group=501)
        context.add_community_files(community_plists, community_files, state.artifacts.files, is_ios27)
        return state.artifacts
    except BaseException:
        state.artifacts.close()
        raise
