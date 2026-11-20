"""Voice-forward mix settings for Violin Prince short-form narration."""

VOICE_PRIORITY_MIX = {
    "ambient_bed_volume": 0.10,
    "violin_bed_volume": 0.12,
    "other_bed_volume": 0.12,
    "voice_volume": 1.40,
    "voice_presence_gain_db": 1.5,
    "voice_presence_frequency_hz": 2600,
    "sidechain_threshold": 0.025,
    "sidechain_ratio": 16,
    "sidechain_attack_ms": 8,
    "sidechain_release_ms": 480,
    "sidechain_knee": 6,
    "creator_take_volume": 0.80,
}


def bed_volume_for(audio_source: str) -> float:
    """Return the conservative starting level for the instrumental bed."""
    if audio_source == "generated_ambient_fallback":
        return VOICE_PRIORITY_MIX["ambient_bed_volume"]
    if audio_source in {"sampled_violin_cc0", "generated_sampled_instrument"}:
        return VOICE_PRIORITY_MIX["violin_bed_volume"]
    return VOICE_PRIORITY_MIX["other_bed_volume"]


def voice_processing_filter(input_label: str = "2:a") -> str:
    """Build a clear, gently levelled narration chain before final loudness control."""
    config = VOICE_PRIORITY_MIX
    return (
        f"[{input_label}]highpass=f=80,"
        f"equalizer=f={config['voice_presence_frequency_hz']}:t=q:w=1.0:"
        f"g={config['voice_presence_gain_db']},"
        "acompressor=threshold=-22dB:ratio=3.5:attack=8:release=180:makeup=1,"
        f"volume={config['voice_volume']:.2f}"
    )


def sidechain_music_filter(
    music_label: str = "bed",
    trigger_label: str = "voice_sc",
    output_label: str = "duckedbed",
) -> str:
    """Lower the music bed more firmly whenever narration is present."""
    config = VOICE_PRIORITY_MIX
    return (
        f"[{music_label}][{trigger_label}]sidechaincompress="
        f"threshold={config['sidechain_threshold']}:"
        f"ratio={config['sidechain_ratio']}:"
        f"attack={config['sidechain_attack_ms']}:"
        f"release={config['sidechain_release_ms']}:"
        f"knee={config['sidechain_knee']}:makeup=1"
        f"[{output_label}]"
    )
