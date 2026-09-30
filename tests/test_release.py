"""The release archives of both editions."""

import hashlib
import zipfile

from scripts import build_release


def test_both_editions_are_built_from_the_same_files(tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1759190400")
    files = build_release.release_files()

    private, company = (
        build_release.build(edition, "9.9.9", files, dist=tmp_path) for edition in ("private", "company")
    )

    assert (private.name, company.name) == ("GhostScribe-v9.9.9.zip", "GhostScribe-Company-v9.9.9.zip")
    entries = {
        path: {name.split("/", 1)[1] for name in zipfile.ZipFile(path).namelist()} for path in (private, company)
    }
    assert entries[company] - entries[private] == {"ghostscribe/EDITION"}  # the only difference
    assert zipfile.ZipFile(company).read("GhostScribe-Company-v9.9.9/ghostscribe/EDITION") == b"company\n"
    checksum = (tmp_path / "GhostScribe-Company-v9.9.9.zip.sha256").read_text(encoding="utf-8")
    assert checksum == f"{hashlib.sha256(company.read_bytes()).hexdigest()}  GhostScribe-Company-v9.9.9.zip\n"
    assert build_release.build("company", "9.9.9", files, dist=tmp_path).read_bytes() == company.read_bytes()


def test_a_local_edition_marker_is_never_packed(tmp_path, monkeypatch):
    package = tmp_path / "ghostscribe"
    package.mkdir()
    (package / "app.py").write_text("", encoding="utf-8")
    (package / "EDITION").write_text("company", encoding="utf-8")  # a developer tries the company edition
    monkeypatch.setattr(build_release, "ROOT", tmp_path)

    packed = {path.relative_to(tmp_path).as_posix() for path in build_release.release_files()}

    assert "ghostscribe/app.py" in packed and "ghostscribe/EDITION" not in packed
