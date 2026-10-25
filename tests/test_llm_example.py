import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class LLMExampleTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "llm_prompt" / "app.py"
        spec = importlib.util.spec_from_file_location("llm_example", path)
        self.app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.app)

    def test_real_cli_result_envelope_and_verbose_history(self):
        result = {"type": "result", "is_error": False, "result": '{"quantity":1}', "usage": {"input_tokens": 10}}
        for envelope in (result, [{"type": "assistant", "message": {}}, result]):
            process = SimpleNamespace(returncode=0, stdout=json.dumps(envelope), stderr="")
            with patch.object(self.app.subprocess, "run", return_value=process) as call:
                observation = self.app.evaluate({"input": "One notebook"})
                self.assertEqual(observation["output"], '{"quantity":1}')
                self.assertEqual(observation["usage"]["input_tokens"], 10)
                self.assertIn("One notebook", call.call_args.kwargs["input"])

    def test_provider_error_is_not_a_quality_score(self):
        result = {"type": "result", "is_error": True, "result": "inference unavailable"}
        process = SimpleNamespace(returncode=0, stdout=json.dumps(result), stderr="")
        with patch.object(self.app.subprocess, "run", return_value=process):
            with self.assertRaisesRegex(RuntimeError, "inference unavailable"):
                self.app.evaluate({"input": "One notebook"})
