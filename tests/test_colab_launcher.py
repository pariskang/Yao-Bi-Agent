from pathlib import Path


def test_colab_launcher_and_readme_support_ngrok_and_multi_provider():
    launcher = Path("colab/launch_yaobi_colab.py").read_text(encoding="utf-8")
    readme = Path("colab/README.md").read_text(encoding="utf-8")
    root_readme = Path("README.md").read_text(encoding="utf-8")

    assert "pyngrok" in launcher and "ngrok.connect" in launcher
    assert "DEFAULT_MODEL_BY_BACKEND" in launcher
    for backend in ["minimax", "poe", "azure", "openai", "anthropic", "transformers", "mock"]:
        assert backend in launcher
        assert backend in readme
    assert "Gemini-3.1-Pro" in readme
    assert "colab.research.google.com" in root_readme and "blob/main/colab/YaoBi_Skill_Colab.ipynb" in root_readme
