# API Dub từ SRT/VTT cho ứng dụng bên thứ ba

Tài liệu này chỉ mô tả luồng tạo **audio lồng tiếng từ file `.srt` hoặc `.vtt`**. Đầu vào không cần video hay audio gốc. Ví dụ dùng một giọng đã clone và lưu trong **Saved voices**; không tạo giọng mới và không cần gửi lại file giọng mẫu.

## Chuẩn bị

- Chạy backend VoiceStudio và cài sẵn một engine hỗ trợ voice cloning. Ví dụ mặc định dùng `http://127.0.0.1:3900` và xuất lời thoại tiếng Việt (`language_code=vi`). Đổi ngôn ngữ trong request nếu file đầu ra dùng ngôn ngữ khác.
- Nếu muốn dịch lời thoại, ứng dụng gọi API phải đưa **văn bản đã dịch** vào `segments[].text` trước khi gọi generate. Bước generate đọc đúng văn bản được gửi, không tự dịch file phụ đề.

## Xác thực và kết nối

**Cùng máy:** backend mặc định chỉ lắng nghe tại `127.0.0.1:3900`. Ứng dụng gọi `http://127.0.0.1:3900` không cần API key hoặc PIN, kể cả khi các cơ chế đó đã được bật cho máy khác.

**Chạy headless trên Windows:** tại thư mục mã nguồn VoiceStudio, nhấp đúp `Start-VoiceStudio-Server.cmd`. Launcher dùng môi trường Python `.venv` đã setup, chỉ chạy backend ở `127.0.0.1:3900`, không mở Electron. Giữ cửa sổ terminal để server tiếp tục chạy; nhấn `Ctrl+C` để dừng. Nếu chưa setup backend, chạy `bun run setup:api` một lần. Có thể kiểm tra server sau khi khởi động bằng `http://127.0.0.1:3900/health`.

**Máy khác:** chạy backend ở chế độ server, đặt một API key mạnh trong môi trường của **tiến trình backend**, rồi gửi cùng key trong header `Authorization` ở **mọi request** của quy trình dưới đây, kể cả SSE và tải file. Ví dụ chạy từ mã nguồn trên máy GPU:

```powershell
# PowerShell trên máy chạy backend (Windows): đặt key rồi chạy launcher LAN.
$env:OMNIVOICE_API_KEY = python -c "import secrets; print(secrets.token_urlsafe(24))"
$env:OMNIVOICE_API_KEY  # Sao chép và lưu key để cấu hình ứng dụng gọi API.
.\Start-VoiceStudio-Server.cmd --lan
```

`--lan` chỉ khởi động khi có `OMNIVOICE_API_KEY`, lắng nghe ở `0.0.0.0:3900` và bật `OMNIVOICE_SERVER_MODE=1`. Nếu dùng cổng này cho Electron hoặc một backend khác, hãy dừng tiến trình đó trước.

```powershell
# Cách chạy thủ công tương đương trên Windows, không dùng launcher.
$env:OMNIVOICE_API_KEY = python -c "import secrets; print(secrets.token_urlsafe(24))"
$env:OMNIVOICE_SERVER_MODE = "1"
uv run uvicorn backend.main:app --host 0.0.0.0 --port 3900
```

```bash
# Bash trên máy chạy backend (Linux/macOS)
export OMNIVOICE_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
export OMNIVOICE_SERVER_MODE=1
uv run uvicorn backend.main:app --host 0.0.0.0 --port 3900
```

Lưu key ở nơi quản lý secret của bạn, không ghi vào mã nguồn hoặc URL. Giới hạn cổng `3900` vào mạng riêng hoặc dùng HTTPS/TLS; HTTP trên mạng không tin cậy làm lộ Bearer key. Phía ứng dụng gọi API đặt `VOICESTUDIO_URL` thành địa chỉ backend và `VOICESTUDIO_API_KEY` bằng **đúng giá trị** `OMNIVOICE_API_KEY` trên backend. Ví dụ:

```http
GET /profiles HTTP/1.1
Host: gpu-box.example:3900
Authorization: Bearer <OMNIVOICE_API_KEY>
```

Nếu bạn bật **Network sharing** trong app và có mã PIN 6 chữ số, các request HTTP từ máy khác cần thêm `X-OmniVoice-Pin: <PIN>`. Nếu đồng thời bật API key, gửi **cả hai** header. PIN thay đổi mỗi lần bật chia sẻ; cách dùng API key ở ví dụ này phù hợp hơn cho tích hợp lâu dài. Python mẫu bên dưới nhận PIN tùy chọn từ `VOICESTUDIO_SHARE_PIN`.

| Phản hồi | Cách xử lý |
| --- | --- |
| `401 {"detail":"API key required"}` | Thiếu hoặc sai Bearer key trên request từ máy khác. |
| `401 {"detail":"PIN required"}` | Network sharing đang yêu cầu PIN; gửi `X-OmniVoice-Pin`. |
| `403` | Request bị từ chối bởi ranh giới quyền hoặc kiểm tra origin; kiểm tra quyền, URL và cấu hình server. |

Ứng dụng server-to-server, CLI và Python `requests` không cần cấu hình CORS. Nếu app bên thứ ba gọi API **trực tiếp từ trình duyệt ở origin khác**, cấu hình `OMNIVOICE_ALLOWED_ORIGINS` trên backend bằng các origin chính xác dạng `scheme://host:port` (không có path hoặc dấu `/` cuối), rồi khởi động lại backend. Giá trị này **thay thế** danh sách mặc định, nên thêm cả `http://localhost:3901`, `http://127.0.0.1:3901` và `app://voicestudio` nếu bạn vẫn dùng các giao diện đó. Không đặt API key trong mã JavaScript công khai của trình duyệt; cho frontend gọi qua backend riêng của ứng dụng bên thứ ba.

## Các endpoint

| Bước | Request | Kết quả cần dùng |
| --- | --- | --- |
| Tìm giọng đã clone | `GET /profiles` | Chọn profile có `kind="clone"` (hoặc `kind=null` với dữ liệu cũ); lấy `id`. |
| Nhập phụ đề | `POST /dub/upload-subtitles` với multipart field `file` | `job_id`, `segments`, `stats`. Chỉ chấp nhận tên file `.srt`/`.vtt`. |
| Tạo audio | `POST /dub/generate/{job_id}` với JSON | `task_id`; đây là tác vụ nền, chưa có file ngay. |
| Theo dõi | `GET /tasks/stream/{task_id}` | Server-Sent Events; chờ `type="done"`, xử lý `error`/`cancelled`. |
| Tải WAV đã ghép | `GET /dub/download-audio/{job_id}?lang=vi` | Một file WAV chứa tất cả cue. |

`GET /dub/download-mp3/{job_id}?lang=vi` xuất MP3. `GET /dub/srt/{job_id}?lang=vi` và `GET /dub/vtt/{job_id}?lang=vi` xuất phụ đề. Job chỉ có phụ đề nên không có video xuất ra. File upload trống, sai phần mở rộng hoặc lớn hơn 8 MB bị từ chối.

Request generate tối thiểu cho một cue:

```json
{
  "language": "Vietnamese",
  "language_code": "vi",
  "segment_ids": ["0"],
  "segments": [
    {
      "start": 1.0,
      "end": 3.2,
      "text": "Lời thoại tiếng Việt đã chuẩn bị.",
      "profile_id": "ID_LAY_TU_GET_PROFILES",
      "cue_source_id": "ID_LAY_TU_SEGMENT_NHAP"
    }
  ]
}
```

Lấy `start`, `end`, `text`, `id` và `cue_source_id` từ `segments` của kết quả upload; `segment_ids` tương ứng với từng `id` theo đúng thứ tự. `profile_id` là ID giọng clone, không phải tên giọng. Giữ `cue_source_id` để dữ liệu cue gốc được nhận diện khi xuất SRT/VTT, nếu `text` vẫn đúng như lúc nhập; sửa hoặc dịch `text` thì backend không dùng lại markup gốc. Có thể kiểm tra `stats.skipped_malformed` và `stats.dropped_overlap` trước khi tạo audio.

## Ví dụ Python hoàn chỉnh

Cài thư viện HTTP cho ứng dụng gọi API: `python -m pip install requests`. Lưu đoạn sau thành `subtitle_dub.py`, rồi chạy `python subtitle_dub.py duong-dan/phu-de.srt` (hoặc `.vtt`). Ví dụ tự tìm giọng clone; nếu có nhiều giọng, đặt `CLONED_VOICE_NAME` bằng **tên chính xác** trong Saved voices, hoặc đặt `CLONED_VOICE_ID`. Không tự chọn một giọng bất kỳ khi kết quả còn mơ hồ.

```python
import json
import os
import sys
from pathlib import Path

import requests


BASE_URL = os.getenv("VOICESTUDIO_URL", "http://127.0.0.1:3900").rstrip("/")
VOICE_ID = os.getenv("CLONED_VOICE_ID", "").strip()
VOICE_NAME = os.getenv("CLONED_VOICE_NAME", "").strip()
LANGUAGE = "Vietnamese"
LANGUAGE_CODE = "vi"


def api_json(response):
    response.raise_for_status()
    return response.json()


def choose_clone(profiles):
    clones = [p for p in profiles if p.get("kind") in (None, "clone")]
    if VOICE_ID:
        matches = [p for p in clones if p["id"] == VOICE_ID]
    elif VOICE_NAME:
        matches = [p for p in clones if p["name"].casefold() == VOICE_NAME.casefold()]
    else:
        matches = clones if len(clones) == 1 else []
    if len(matches) != 1:
        choices = ", ".join(f"{p['name']} ({p['id']})" for p in clones) or "không có"
        raise SystemExit(
            "Không xác định được duy nhất giọng clone. "
            f"Đặt CLONED_VOICE_NAME hoặc CLONED_VOICE_ID. Các giọng hiện có: {choices}"
        )
    return matches[0]


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Cách chạy: python subtitle_dub.py <file.srt|file.vtt>")
    source = Path(sys.argv[1])
    if not source.is_file() or source.suffix.lower() not in {".srt", ".vtt"}:
        raise SystemExit("Cần một file .srt hoặc .vtt tồn tại")

    session = requests.Session()
    api_key = os.getenv("VOICESTUDIO_API_KEY", "").strip()
    if api_key:
        session.headers["Authorization"] = f"Bearer {api_key}"
    share_pin = os.getenv("VOICESTUDIO_SHARE_PIN", "").strip()
    if share_pin:
        session.headers["X-OmniVoice-Pin"] = share_pin

    profiles = api_json(session.get(f"{BASE_URL}/profiles", timeout=30))
    clone = choose_clone(profiles)
    print(f"Dùng giọng clone: {clone['name']} ({clone['id']})")

    with source.open("rb") as subtitle_file:
        uploaded = api_json(session.post(
            f"{BASE_URL}/dub/upload-subtitles",
            files={"file": (source.name, subtitle_file, "text/plain")},
            timeout=120,
        ))
    job_id = uploaded["job_id"]
    print(f"Job: {job_id}; cue hợp lệ: {uploaded['stats']['imported']}")

    imported = uploaded["segments"]
    segments = []
    for cue in imported:
        segment = {
            "start": cue["start"],
            "end": cue["end"],
            "text": cue["text"],
            "profile_id": clone["id"],
        }
        if cue.get("cue_source_id"):
            segment["cue_source_id"] = cue["cue_source_id"]
        segments.append(segment)

    task = api_json(session.post(
        f"{BASE_URL}/dub/generate/{job_id}",
        json={
            "language": LANGUAGE,
            "language_code": LANGUAGE_CODE,
            "segment_ids": [str(cue["id"]) for cue in imported],
            "segments": segments,
        },
        timeout=120,
    ))
    task_id = task["task_id"]
    print(f"Task: {task_id}")

    completed = False
    with session.get(
        f"{BASE_URL}/tasks/stream/{task_id}", stream=True, timeout=(10, None)
    ) as stream:
        stream.raise_for_status()
        for raw_line in stream.iter_lines():
            if not raw_line.startswith(b"data:"):
                continue  # Dòng trống hoặc SSE keepalive.
            event = json.loads(raw_line[5:].strip().decode("utf-8"))
            event_type = event.get("type")
            if event_type == "error":
                raise RuntimeError(event.get("error") or event.get("reason") or str(event))
            if event_type == "cancelled":
                raise RuntimeError("Tác vụ đã bị hủy")
            if event_type == "done":
                completed = True
                break
    if not completed:
        raise RuntimeError("SSE kết thúc trước khi tác vụ báo done")

    output = source.with_name(f"{source.stem}.dub.vi.wav")
    with session.get(
        f"{BASE_URL}/dub/download-audio/{job_id}",
        params={"lang": LANGUAGE_CODE}, stream=True, timeout=(10, 300),
    ) as audio:
        audio.raise_for_status()
        with output.open("wb") as file:
            for chunk in audio.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    file.write(chunk)
    print(f"Đã lưu: {output.resolve()}")


if __name__ == "__main__":
    main()
```

Ví dụ đặt biến môi trường trong PowerShell khi có nhiều giọng clone:

```powershell
$env:CLONED_VOICE_NAME = "Tên giọng đã lưu trong Saved voices"
python subtitle_dub.py "C:\recording\phu-de.vtt"
```

Khi gọi backend từ máy khác, cấu hình môi trường **trên máy chạy ứng dụng gọi API** trước khi chạy script:

```powershell
$env:VOICESTUDIO_URL = "https://gpu-box.example"
$env:VOICESTUDIO_API_KEY = "<cùng key với OMNIVOICE_API_KEY trên backend>"
# Chỉ cần dòng sau nếu Network sharing có PIN:
$env:VOICESTUDIO_SHARE_PIN = "<PIN 6 chữ số>"
python subtitle_dub.py "C:\recording\phu-de.vtt"
```

Không gắn API key vào URL.

## Quy tắc thời lượng

- Mỗi cue bắt đầu tại `start` của phụ đề. Khoảng lặng giữa các cue được giữ lại trong WAV đã ghép.
- Nếu lời thoại dài hơn cue, backend tăng tốc audio mà giữ cao độ, tối đa **15%** (`1.15×`). Nếu vẫn chưa đủ, backend giữ trọn lời và cho audio kéo dài qua `end`; audio của cue sau có thể chồng lên và được trộn vào cùng WAV.
- Nếu lời thoại ngắn hơn hoặc bằng cue, audio giữ tốc độ tự nhiên; backend không kéo giãn để lấp đầy cue.
- Khi nhập file, các cue nguồn bị chồng thời gian được parser sắp xếp và xử lý; `stats.dropped_overlap` cho biết số cue bị bỏ vì chồng lấn. Quy tắc trộn chồng ở trên áp dụng cho **audio sinh ra** kéo dài quá cue sau khi nhập.
- Job nhập phụ đề luôn dùng chiến lược `subtitle_cues` ở backend. Trường `timing_strategy` trong request không đổi quy tắc này. Sự kiện `done` có `fit_status` theo từng cue (`fits` hoặc `cue_extended`, kèm `audio_rate` và `cue_overflow_s`) để ứng dụng hiển thị hoặc ghi log.

HTTP `200` từ `/dub/generate/{job_id}` chỉ có nghĩa là tác vụ đã được nhận. Chỉ tải file sau sự kiện SSE `done`. Nếu stream ngắt trước sự kiện cuối, ứng dụng nên nối lại vào cùng `task_id` qua `/tasks/stream/{task_id}?after_seq=N`; không gửi lại generate chỉ vì mất kết nối. `400` thường là file/cue không hợp lệ, `404` là job/task không tồn tại, và `409` có thể là engine/model chưa được cài.
