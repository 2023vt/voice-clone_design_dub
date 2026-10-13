# Subtitle cue compaction

`POST /subtitles/compaction/preview` combines adjacent subtitle cues without
changing their source order. The first cue ID is retained so downstream edits
and retries remain stable.

The documented default joins cues separated by at most 250 milliseconds, up to
a combined duration of seven seconds. Cues from different speakers remain
separate by default. Callers may change the gap, duration, speaker rule, and
whether merged text uses a space or newline.

Empty options use the documented defaults. Invalid durations, gaps, and cue
time ranges are rejected. The deprecated `compact` boolean is an alias for the
shared default policy.
