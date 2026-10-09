# Hindi

How to get the most natural Hindi out of VoiceStudio, and what the app does
to Hindi text on its own. Everything here works the same on macOS, Windows
and Linux; nothing needs a download beyond the engine you already use.

## Best Hindi voice clone

- **Write in Devanagari.** Roman "Hinglish" (`kya haal hai`) is read as
  English by every engine, with English vowels. Type `क्या हाल है` and the
  engine switches to Hindi pronunciation. Mixed scripts are fine: English
  product names inside a Devanagari sentence are read as English words.
- **Pick Hindi as the language**, not Auto. Auto leaves detection to the
  engine; Hindi turns on the Hindi number, time and rupee reading below and
  the `से` reading of ranges (`20~30 सेकंड`).
- **Reference clip in Hindi.** Zero-shot cloning copies the delivery of the
  reference, so a 5–15 s clip of the speaker talking naturally *in Hindi*
  clones Hindi prosody; an English clip clones an English cadence. Clean,
  close-mic, no music. If you type the transcript yourself, type it in
  Devanagari.
- **Engines that clone Hindi:** the default VoiceStudio (OmniVoice) engine,
  and [VoxCPM2](engines/voxcpm2.md) (48 kHz, Hindi among its 30 languages).
  Try both with the same clip — they trade off differently per speaker.
  IndexTTS 2, CosyVoice 3, Supertonic-3 and KittenTTS do not do Hindi.
- **Ready-made Hindi voices.** The Voice Gallery ships **Hindi Documentary**
  (deep, dramatic nature-reel narrator) and **Hindi Comedy** (bright, quick
  "ulti duniya"-style narrator) next to the Hindi Narrator, Explainer and
  Companion. Use one as-is, or as a starting point for Voice Design.
- **Pacing.** End sentences with the danda (`।`) or a full stop — both split
  chunks and set the gap length. `[pause 500ms]` works anywhere. Turn on
  **Sound more human** in the Audio quality popover for breaths and room
  tone ([audio-quality.md](audio-quality.md)).
- **Pronunciation.** For a loanword or a name the engine gets wrong, add a
  respelling to the pronunciation dictionary or inline as `[[...]]`
  ([expressive-speech.md](expressive-speech.md)).

## What Hindi text normalization does

A Hindi script that reaches the engine with digits in it gets those digits
read in English, or garbled. With the language set to Hindi (display name
or `hi`, `hi-IN`), VoiceStudio rewrites them the way a Hindi reader says
them, before synthesis and before the pronunciation dictionary:

| You write | The engine hears |
|---|---|
| `42 लोग` | `बयालीस लोग` |
| `150 रुपये` | `एक सौ पचास रुपये` |
| `1984 की कहानी` | `उन्नीस सौ चौरासी की कहानी` (1100–1999 use the spoken सौ form) |
| `2026 में` | `दो हज़ार छब्बीस में` |
| `150000` / `1,50,000` | `एक लाख पचास हज़ार` |
| `₹500` / `Rs. 500` / `रु. 500` | `पाँच सौ रुपये` (`₹1` → `एक रुपया`, `₹5.50` → `पाँच रुपये पचास पैसे`) |
| `10:30 बजे` | `साढ़े दस बजे` (`1:30` → `डेढ़`, `2:30` → `ढाई`, `10:15` → `सवा दस`, `10:45` → `पौने ग्यारह`) |
| `10:00` | `दस बजे` |
| `10:20 बजे` | `दस बजकर बीस मिनट पर` |
| `5वीं कक्षा` / `1वां दिन` | `पाँचवीं कक्षा` / `पहला दिन` |
| `50%` | `पचास प्रतिशत` |
| `3.5 किलोमीटर` | `तीन दशमलव पाँच किलोमीटर` |
| `२०२६` | `दो हज़ार छब्बीस` (Devanagari digits are digits) |
| `20~30 सेकंड` | `बीस से तीस सेकंड` |
| `डॉ. शर्मा`, `Dr. शर्मा`, `प्रो.`, `Mr.`, `Mrs.`, `Ms.` | `डॉक्टर शर्मा`, `प्रोफ़ेसर`, `मिस्टर`, `मिसेज़`, `मिस` |

The same conservative rules as every other language apply: `1,000` (plain
thousands grouping), `3-5`, `007`, numbers of seven or more digits, digits
glued to a word (`कक्षा10`), `12:34:56` and anything inside `[...]` are left
exactly as written. Crores are out of range. The pass is idempotent and can
be switched off with `OMNIVOICE_TEXT_NORMALIZATION=0`.
