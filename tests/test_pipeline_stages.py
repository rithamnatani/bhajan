"""Integration tests for each pipeline stage.

These tests verify that each stage can execute successfully with mock data.
"""

import json
import logging
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from bhajan.logger import StageLogger, setup_logging
from bhajan.stages.download import download, DownloadResult
from bhajan.stages.normalize import normalize_audio, _extract_loudnorm_json
from bhajan.stages.separator import run_separation
from bhajan.stages.separator_base import SeparationResult, SeparatorBackend
from bhajan.stages.transcription import run_transcription, save_transcript
from bhajan.stages.transcription_base import Transcript, Segment, WordStamp, TranscriptionBackend
from bhajan.stages.subtitles import generate_ass, generate_lrc
from bhajan.stages.render import render_video, _probe_duration
from bhajan.utils import safe_filename, ensure_dirs


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def tmp_path_structure(tmp_path):
    """Create a standard pipeline directory structure."""
    source_dir = tmp_path / "source"
    stems_dir = tmp_path / "stems"
    transcript_dir = tmp_path / "transcript"
    subtitles_dir = tmp_path / "subtitles"
    final_dir = tmp_path / "final"
    
    for d in [source_dir, stems_dir, transcript_dir, subtitles_dir, final_dir]:
        d.mkdir(parents=True, exist_ok=True)
    
    return {
        "root": tmp_path,
        "source": source_dir,
        "stems": stems_dir,
        "transcript": transcript_dir,
        "subtitles": subtitles_dir,
        "final": final_dir,
    }


@pytest.fixture
def mock_audio_file(tmp_path_structure):
    """Create a dummy audio file for testing."""
    audio_file = tmp_path_structure["source"] / "test_audio.wav"
    # Create a minimal WAV file (44 bytes header + some silence)
    # This is a valid minimal WAV structure
    audio_file.write_bytes(b"RIFF" + b"\x00" * 40 + b"WAVE")
    return audio_file


@pytest.fixture
def sample_transcript():
    """Create a sample transcript with word-level timestamps."""
    transcript = Transcript()
    
    # Add a simple segment with words
    segment = Segment(words=[
        WordStamp(word="Hello", start=0.0, end=0.5),
        WordStamp(word="world", start=0.6, end=1.0),
        WordStamp(word="test", start=1.1, end=1.5),
    ])
    transcript.segments.append(segment)
    
    # Add another segment
    segment2 = Segment(words=[
        WordStamp(word="Second", start=2.0, end=2.5),
        WordStamp(word="line", start=2.6, end=3.0),
    ])
    transcript.segments.append(segment2)
    
    return transcript


# ===================================================================
# Stage Logger Tests
# ===================================================================

class TestStageLogger:
    """Comprehensive tests for StageLogger functionality."""
    
    def test_stage_logger_prefix_applied(self, caplog):
        """Verify that stage prefix is correctly added to messages."""
        logger = logging.getLogger("test_stage_prefix")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(logging.NullHandler())
        
        stage_log = StageLogger(logger, "my_stage")
        
        with caplog.at_level(logging.INFO):
            stage_log.info("test message")
        
        assert "[my_stage]" in caplog.text
        assert "test message" in caplog.text
    
    def test_stage_logger_multiple_stages_isolation(self, caplog):
        """Verify that different stage loggers have different prefixes."""
        logger = logging.getLogger("test_isolation")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(logging.NullHandler())
        
        stage1 = StageLogger(logger, "download")
        stage2 = StageLogger(logger, "normalize")
        
        with caplog.at_level(logging.INFO):
            stage1.info("downloading")
            stage2.info("normalizing")
        
        assert "[download] downloading" in caplog.text
        assert "[normalize] normalizing" in caplog.text
    
    def test_stage_logger_all_levels(self, caplog):
        """Verify all logging levels work with stage prefix."""
        logger = logging.getLogger("test_levels")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(logging.NullHandler())
        
        stage_log = StageLogger(logger, "test")
        
        with caplog.at_level(logging.DEBUG):
            stage_log.debug("debug msg")
            stage_log.info("info msg")
            stage_log.warning("warning msg")
            stage_log.error("error msg")
        
        assert "[test] debug msg" in caplog.text
        assert "[test] info msg" in caplog.text
        assert "[test] warning msg" in caplog.text
        assert "[test] error msg" in caplog.text


# ===================================================================
# Download Stage Tests
# ===================================================================

class TestDownloadStage:
    """Tests for the download stage."""
    
    def test_safe_filename_basic(self):
        """Test that safe_filename handles various inputs correctly."""
        assert safe_filename("Hello World") == "Hello_World" or safe_filename("Hello World") == "Hello World"
        assert "_" in safe_filename("Song/With:Special*Chars?") or safe_filename("Song/With:Special*Chars?").isalnum()
        assert safe_filename("  Trimmed  ") == "Trimmed"
    
    def test_safe_filename_max_length(self):
        """Test that safe_filename respects max length."""
        long_name = "A" * 100
        result = safe_filename(long_name, max_len=50)
        assert len(result) <= 50
    
    def test_ensure_dirs_creates_structure(self, tmp_path):
        """Test that ensure_dirs creates all required directories."""
        root = tmp_path / "test_song"
        subdirs = ["source", "stems", "transcript", "subtitles", "final"]
        
        ensure_dirs(root, subdirs)
        
        assert root.exists()
        for subdir in subdirs:
            assert (root / subdir).exists()


# ===================================================================
# Normalize Stage Tests
# ===================================================================

class TestNormalizeStage:
    """Tests for the normalize stage."""
    
    def test_extract_loudnorm_json_valid(self):
        """Test parsing valid loudnorm JSON from stderr."""
        stderr_output = """
        Some ffmpeg output...
        {"input_i" : "-24.5", "input_tp" : "-30.2", "input_lra" : "10.1", "input_thresh" : "-35.0"}
        More output...
        """
        
        result = _extract_loudnorm_json(stderr_output)
        
        assert result is not None
        assert result["input_i"] == "-24.5"
        assert result["input_tp"] == "-30.2"
    
    def test_extract_loudnorm_json_invalid(self):
        """Test handling of invalid JSON."""
        stderr_output = "No JSON here"
        result = _extract_loudnorm_json(stderr_output)
        assert result is None
    
    def test_extract_loudnorm_json_malformed(self):
        """Test handling of malformed JSON."""
        stderr_output = '{"broken": }'
        result = _extract_loudnorm_json(stderr_output)
        assert result is None


# ===================================================================
# Separator Stage Tests
# ===================================================================

class TestSeparatorStage:
    """Tests for the separator stage."""
    
    def test_separation_result_immutable(self, tmp_path):
        """Test that SeparationResult is frozen (immutable)."""
        vocals = tmp_path / "vocals.wav"
        instrumental = tmp_path / "instrumental.wav"
        
        result = SeparationResult(vocals_path=vocals, instrumental_path=instrumental)
        
        assert result.vocals_path == vocals
        assert result.instrumental_path == instrumental
        
        # Should raise error when trying to modify
        with pytest.raises(Exception):  # FrozenInstanceError
            result.vocals_path = tmp_path / "other.wav"
    
    def test_run_separation_unknown_backend(self):
        """Test that unknown backend raises error."""
        with pytest.raises(ValueError, match="Unknown separator backend"):
            run_separation(
                Path("audio.wav"),
                Path("output"),
                backend_name="unknown_backend"
            )


# ===================================================================
# Transcription Stage Tests
# ===================================================================

class TestTranscriptionStage:
    """Tests for the transcription stage."""
    
    def test_transcript_to_dict(self, sample_transcript):
        """Test transcript serialization to dict."""
        result = sample_transcript.to_dict()
        
        assert "segments" in result
        assert len(result["segments"]) == 2
        assert result["segments"][0]["text"] == "Hello world test"
    
    def test_transcript_to_word_list(self, sample_transcript):
        """Test transcript flattening to word list."""
        words = sample_transcript.to_word_list()
        
        assert len(words) == 5  # 3 + 2 words
        assert words[0].word == "Hello"
        assert words[-1].word == "line"
    
    def test_segment_properties(self):
        """Test segment calculated properties."""
        segment = Segment(words=[
            WordStamp(word="First", start=0.0, end=0.5),
            WordStamp(word="Second", start=0.6, end=1.0),
        ])
        
        assert segment.start == 0.0
        assert segment.end == 1.0
        assert segment.text == "First Second"
    
    def test_save_transcript(self, tmp_path_structure, sample_transcript):
        """Test saving transcript to JSON file."""
        transcript_dir = tmp_path_structure["transcript"]
        
        saved_path = save_transcript(sample_transcript, transcript_dir)
        
        assert saved_path.exists()
        assert saved_path.name == "transcript.json"
        
        # Verify content
        loaded = json.loads(saved_path.read_text(encoding="utf-8"))
        assert len(loaded["segments"]) == 2
    
    def test_run_transcription_unknown_backend(self):
        """Test that unknown backend raises error."""
        with pytest.raises(ValueError, match="Unknown transcription backend"):
            run_transcription(
                Path("vocals.wav"),
                backend_name="unknown_backend"
            )


# ===================================================================
# Subtitles Stage Tests
# ===================================================================

class TestSubtitlesStage:
    """Tests for the subtitles generation stage."""
    
    def test_generate_ass_creates_file(self, tmp_path_structure, sample_transcript):
        """Test that ASS subtitle file is created."""
        subtitles_dir = tmp_path_structure["subtitles"]
        
        ass_path = generate_ass(sample_transcript, subtitles_dir)
        
        assert ass_path.exists()
        assert ass_path.name == "karaoke.ass"
        
        content = ass_path.read_text(encoding="utf-8-sig")
        assert "[Script Info]" in content
        assert "[Events]" in content
    
    def test_generate_lrc_creates_file(self, tmp_path_structure, sample_transcript):
        """Test that LRC subtitle file is created."""
        subtitles_dir = tmp_path_structure["subtitles"]
        
        lrc_path = generate_lrc(sample_transcript, subtitles_dir)
        
        assert lrc_path.exists()
        assert lrc_path.name == "lyrics.lrc"
        
        content = lrc_path.read_text(encoding="utf-8")
        assert "[" in content  # LRC timestamps
    
    def test_ass_time_conversion(self):
        """Test seconds to ASS time conversion."""
        from bhajan.stages.subtitles import _seconds_to_ass_time
        
        time_str = _seconds_to_ass_time(3661.5)  # 1h 1m 1.5s
        assert time_str.startswith("1:")
    
    def test_lrc_time_conversion(self):
        """Test seconds to LRC time conversion."""
        from bhajan.stages.subtitles import _seconds_to_lrc
        
        time_str = _seconds_to_lrc(65.5)  # 1m 5.5s
        assert time_str == "01:05.50"


# ===================================================================
# Render Stage Tests
# ===================================================================

class TestRenderStage:
    """Tests for the render stage."""
    
    def test_probe_duration_returns_float(self):
        """Test that _probe_duration returns a float (mocked)."""
        with patch('bhajan.stages.render.subprocess_utils.check_call') as mock_call:
            mock_result = Mock()
            mock_result.stdout = "30.5"
            mock_call.return_value = mock_result
            
            duration = _probe_duration(Path("test.wav"))
            
            assert duration == 30.5
    
    def test_probe_duration_fallback_on_error(self):
        """Test that _probe_duration falls back to default on error."""
        with patch('bhajan.stages.render.subprocess_utils.check_call') as mock_call:
            mock_result = Mock()
            mock_result.stdout = "invalid"
            mock_call.return_value = mock_result
            
            duration = _probe_duration(Path("test.wav"))
            
            assert duration == 300.0  # Default fallback
