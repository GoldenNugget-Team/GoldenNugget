from .icon_themes.icon_themes_tweak import IconThemesTweak
from .posterboard.posterboard_tweak import PosterboardTweak
from .posterboard.template_options.templates_tweak import TemplatesTweak
from .status_bar.status_bar_tweak import StatusBarTweak
from .store import TweakStore, default_changes
from .tweak_classes import AdvancedPlistTweak, BasicPlistTweak, NullifyFileTweak
from .tweak_names import TweakID

tweaks = TweakStore({
    ## PosterBoard
    TweakID.PosterBoard: PosterboardTweak(),

    ## Templates
    TweakID.Templates: TemplatesTweak(),

    ## Status Bar
    TweakID.StatusBar: StatusBarTweak(),

    ## Icon Themes
    TweakID.IconThemes: IconThemesTweak(),

}, changes=default_changes)
