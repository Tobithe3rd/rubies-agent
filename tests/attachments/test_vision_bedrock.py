import io
from pathlib import Path

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError
from PIL import Image

from attachments.models import AttachmentRejected
from attachments.vision.base import get_vision_extractor
from attachments.vision.bedrock import BedrockVisionExtractor
from attachments.vision.mock import MockVisionExtractor
from tests.attachments import fixtures as fx
from tests.attachments.profiles import make_vision

VISION = make_vision(provider="bedrock", temperature=0.2, max_output_tokens=123)


class FakeClient:
    def __init__(self, response=None, error=None):
        self.calls = []
        self.response = response or {
            "output": {"message": {"content": [{"text": "Transcribed text."}]}},
            "usage": {"inputTokens": 100, "outputTokens": 20},
        }
        self.error = error

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def make_extractor(client):
    return BedrockVisionExtractor(VISION, client=client)


class TestBedrockRequest:
    def test_image_request_shape_and_prompt(self):
        client = FakeClient()
        result = make_extractor(client).transcribe(fx.png_bytes(), "png")
        kwargs = client.calls[0]
        assert kwargs["modelId"] == VISION.model_id
        assert kwargs["inferenceConfig"] == {"temperature": 0.2, "maxTokens": 123}
        content = kwargs["messages"][0]["content"]
        assert content[0]["image"]["format"] == "png"
        assert content[0]["image"]["source"]["bytes"]
        assert content[1]["text"] == Path(VISION.prompt_path).read_text()
        assert result.text == "Transcribed text."
        assert (result.input_tokens, result.output_tokens) == (100, 20)

    def test_jpeg_reencoded_without_exif(self):
        exif = Image.Exif()
        exif[0x010F] = "SpikeCam"
        buf = io.BytesIO()
        Image.open(io.BytesIO(fx.jpeg_bytes())).save(buf, "JPEG", exif=exif.tobytes())
        with_exif = buf.getvalue()
        assert len(Image.open(io.BytesIO(with_exif)).getexif()) > 0

        client = FakeClient()
        make_extractor(client).transcribe(with_exif, "jpeg")
        sent = client.calls[0]["messages"][0]["content"][0]["image"]["source"]["bytes"]
        assert len(Image.open(io.BytesIO(sent)).getexif()) == 0

    def test_pdf_document_block_name(self):
        client = FakeClient()
        make_extractor(client).transcribe(fx.pdf_bytes(), "pdf")
        document = client.calls[0]["messages"][0]["content"][0]["document"]
        assert document["name"] == "Document 1"
        assert document["format"] == "pdf"

    def test_empty_model_output_becomes_no_text(self):
        response = {"output": {"message": {"content": [{"text": ""}]}}, "usage": {}}
        result = make_extractor(FakeClient(response)).transcribe(fx.png_bytes(), "png")
        assert result.text == "NO_TEXT"

    def test_missing_usage_is_none(self):
        response = {"output": {"message": {"content": [{"text": "ok"}]}}}
        result = make_extractor(FakeClient(response)).transcribe(fx.png_bytes(), "png")
        assert result.input_tokens is None and result.output_tokens is None


class TestBedrockErrors:
    @pytest.mark.parametrize("error", [
        ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "Converse"),
        ReadTimeoutError(endpoint_url="https://example.invalid"),
        RuntimeError("UniqueSecretPromptBody"),
    ])
    def test_errors_map_to_extraction_unavailable(self, error):
        with pytest.raises(AttachmentRejected) as info:
            make_extractor(FakeClient(error=error)).transcribe(fx.png_bytes(), "png")
        assert info.value.code == "extraction_unavailable"
        message = str(info.value)
        assert "UniqueSecretPromptBody" not in message
        assert "Transcription tool" not in message
        assert "PNG" not in message


class TestFactory:
    def test_mock_provider(self):
        extractor = get_vision_extractor(make_vision(provider="mock"))
        assert isinstance(extractor, MockVisionExtractor)

    def test_bedrock_provider_built_without_network(self):
        extractor = get_vision_extractor(make_vision(provider="bedrock"))
        assert isinstance(extractor, BedrockVisionExtractor)
        assert extractor.prompt
