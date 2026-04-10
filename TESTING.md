# Testing Guide for Bhajan

This document explains how to run tests and understand the test coverage for the bhajan karaoke pipeline.

## Quick Start

Run all tests:

```bash
uv run pytest
```

Run tests with verbose output:

```bash
uv run pytest -v
```

## Test Structure

The test suite is organized by component:

- **`test_logger.py`**: Unit tests for the `StageLogger` logging utility
- **`test_pipeline_stages.py`**: Integration tests for each pipeline stage

## Running Specific Tests

Run a specific test file:

```bash
uv run pytest tests/test_logger.py
```

Run a specific test class:

```bash
uv run pytest tests/test_pipeline_stages.py::TestStageLogger
```

Run a specific test:

```bash
uv run pytest tests/test_logger.py::test_stage_logger_info_with_args
```

## Test Markers

Tests can be filtered using pytest markers:

- `slow`: Tests that take a long time to run
- `integration`: Tests that require external services or dependencies

Run only fast tests:

```bash
uv run pytest -m "not slow"
```

## Debugging Failed Tests

### Enable Verbose Logging

Many issues can be diagnosed by enabling debug-level logging:

```bash
uv run bhajan "<youtube_url>" --verbose
```

This will show:
- All pipeline stage transitions
- File paths and sizes
- Command execution details
- Error messages with context

### Common Issues

#### StageLogger Error: "takes 2 positional arguments but 3 were given"

**Fixed**: The `StageLogger` class now properly supports printf-style formatting:

```python
stage.info("Value: %d", 42)  # ✓ Works correctly
stage.info("Path: %s", path)  # ✓ Works correctly
```

#### Missing Dependencies

If tests fail due to missing packages:

```bash
uv sync --dev
```

#### ffmpeg/ffprobe Not Found

These external tools must be installed and on your PATH:

```bash
# Windows
winget install ffmpeg

# macOS
brew install ffmpeg

# Linux
sudo apt install ffmpeg
```

## Test Coverage

To check test coverage (requires pytest-cov):

```bash
uv add --dev pytest-cov
uv run pytest --cov=bhajan --cov-report=html
```

Then open `htmlcov/index.html` to see the coverage report.

## Continuous Integration

All tests should pass before committing code. Run the full test suite:

```bash
uv run pytest --tb=short
```

## Writing New Tests

When adding new features or fixing bugs, please add corresponding tests:

1. **Unit tests**: Test individual functions/classes in isolation
2. **Integration tests**: Test how components work together
3. **End-to-end tests**: Test the full pipeline (marked as `@pytest.mark.slow`)

### Example Test Structure

```python
class TestNewFeature:
    """Tests for the new feature."""
    
    def test_basic_functionality(self, tmp_path):
        """Test the basic use case."""
        # Arrange
        input_data = create_test_data(tmp_path)
        
        # Act
        result = process_data(input_data)
        
        # Assert
        assert result.expected_outcome is True
    
    def test_edge_case(self):
        """Test an edge case."""
        with pytest.raises(ValueError):
            process_invalid_data(None)
```

## Troubleshooting

### Tests Pass But Tool Fails

This usually means:
1. External dependencies (ffmpeg, demucs, whisper) are not installed
2. Network issues preventing downloads
3. Insufficient disk space for intermediate files

Run with `--verbose` flag to see detailed error messages:

```bash
uv run bhajan "https://youtube.com/watch?v=..." --verbose
```

### Out of Memory Errors

The pipeline processes audio in memory. For large files, ensure:
- At least 4GB RAM for whisper transcription
- At least 8GB RAM for demucs separation
- Sufficient disk space (5-10x the audio file size)

### Windows-Specific Issues

- Path separators: Windows uses `\` instead of `/`
- Long paths: Enable long path support in Windows
- File locks: Ensure no other process has the files open

## Performance Tips

1. **Use SSD**: Intermediate files are read/written frequently
2. **Use CUDA**: If you have an NVIDIA GPU, add `--device cuda`
3. **Skip stages**: When debugging, use skip flags:
   ```bash
   uv run bhajan "<url>" --skip-download --skip-separate
   ```

## Getting Help

If tests fail and you can't diagnose the issue:

1. Run with `--verbose` flag
2. Check the output directory for partial results
3. Ensure all external tools are installed:
   ```bash
   ffmpeg -version
   demucs --version
   python -c "import faster_whisper; print(faster_whisper.__version__)"
   ```
4. Open an issue with the full test output and system information
