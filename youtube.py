"""유튜브 자막 추출.

원본: C:\\GIT\\Moons_Company\\agents\\scrap_agent.py 의 실전 검증된 3단 폴백.
이식하며 바꾼 것: async 제거(내부가 동기였음), API 객체 주입화(테스트가 네트워크를 안 타도록).
"""
import re


def format_time(seconds):
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def extract_youtube_id(url):
    m = re.search(
        r'(https?://)?(www\.)?'
        r'(youtube|youtu|youtube-nocookie)\.(com|be)/'
        r'(watch\?v=|embed/|v/|shorts/|live/|.+\?v=)?([^&=%\?/]{11})', url or "")
    return m.group(6) if m else None


def _attr(item, name):
    """자막 항목이 객체일 수도 dict 일 수도 있다(라이브러리 버전 차이)."""
    if hasattr(item, name):
        return getattr(item, name)
    if isinstance(item, dict):
        return item.get(name)
    return None


def merge_transcripts(srt, interval_sec=30):
    """30초 단위로 병합해 텍스트 밀도를 높이고 토큰을 아낀다."""
    if not srt:
        return ""
    merged, chunk = [], []
    current_start = _attr(srt[0], "start") or 0.0
    for item in srt:
        start = _attr(item, "start") or 0.0
        text = _attr(item, "text") or ""
        if not chunk:
            current_start, chunk = start, [text]
        elif start - current_start >= interval_sec:
            merged.append(f"[{format_time(current_start)}] {' '.join(chunk)}")
            current_start, chunk = start, [text]
        else:
            chunk.append(text)
    if chunk:
        merged.append(f"[{format_time(current_start)}] {' '.join(chunk)}")
    return "\n".join(merged)


def get_transcript(video_id, api=None):
    """3단 폴백: 수동 ko/en -> 목록 조회 -> en 을 ko 로 번역. 전부 실패하면 None."""
    if api is None:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            api = YouTubeTranscriptApi()
        except Exception as e:
            print(f"[youtube] 라이브러리 연동 실패: {e}")
            return None
    try:
        return merge_transcripts(api.fetch(video_id, languages=['ko', 'en']))
    except Exception as e1:
        print(f"[youtube] 자막 1차 실패: {e1}")
    try:
        listing = api.list(video_id)
    except Exception as e:
        print(f"[youtube] 자막 목록 조회 실패: {e}")
        return None
    try:
        return merge_transcripts(listing.find_transcript(['ko', 'en']).fetch())
    except Exception as e2:
        print(f"[youtube] 자막 2차 실패: {e2}")
    try:
        return merge_transcripts(listing.find_transcript(['en']).translate('ko').fetch())
    except Exception as e3:
        print(f"[youtube] 자막 3차 실패: {e3}")
        return None
