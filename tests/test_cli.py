from studio_transcribe.cli import main


def test_eval_command_reports_wer(tmp_path, capsys):
    ref = tmp_path / "ref.txt"
    hyp = tmp_path / "hyp.txt"
    ref.write_text("the cat sat on the mat", encoding="utf-8")
    hyp.write_text("the cat sat on a mat", encoding="utf-8")

    rc = main(["eval", str(ref), str(hyp)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "WER:" in out
    assert "CER:" in out


def test_version_command(capsys):
    rc = main(["version"])
    assert rc == 0
    assert capsys.readouterr().out.strip()
