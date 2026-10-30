RETIRED_FEATURE_FLAG_TYPES = frozenset({
    "FeatureFlagTweak",
    "GlassFeatureFlagTweak",
    "UIKitInternalBooleanTweak",
    "UIKitInternalScrollDurationTweak",
    "DirectionalScrollDurationTweak",
    "DiscreteScrollDurationTweak",
    "UIKitAnimationScaleTweak",
})


def is_retired_feature_flag(entry):
    if not isinstance(entry, dict):
        return False
    kind = entry.get("type")
    return isinstance(kind, str) and kind in RETIRED_FEATURE_FLAG_TYPES
