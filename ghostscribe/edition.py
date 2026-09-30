"""
Editions of GhostScribe, built from the same code:

- private: everything, including the optional sentiment mode, for use at your own responsibility.
- company: for companies, associations and other organizations. The EU AI Act prohibits emotion recognition at the
  workplace, whatever the status of the people (employees, volunteers, candidates), so the sentiment mode is not
  available; every recording needs the confirmation that all participants agreed; interviews are documented without
  assessing the person; the minutes say that they were generated; the audio is deleted 30 days after the analysis
  by default.

The company release archive contains the file ghostscribe/EDITION with the word "company". It is part of the program,
not of .env, so that nobody switches the company rules off by accident. A source checkout is the private edition.
"""

from pathlib import Path

EDITION_FILE = Path(__file__).resolve().parent / "EDITION"
PRIVATE, COMPANY = "private", "company"


def edition() -> str:
    """The edition of this installation. An unreadable or unknown marker counts as company: the stricter one."""
    try:
        name = EDITION_FILE.read_text(encoding="utf-8").strip().lower()
    except FileNotFoundError:
        return PRIVATE
    except OSError:
        return COMPANY
    return PRIVATE if name == PRIVATE else COMPANY


def is_company() -> bool:
    return edition() == COMPANY
