import cv2
import numpy as np
import pytest

from omr_core.branding import Institute, check, from_json, prepare_logo, to_json


def test_a_logo_is_trimmed_sized_and_checked():
    page = np.full((2000, 3000, 4), 0, np.uint8)  # transparent, with a red disc in the middle
    cv2.circle(page, (1500, 1000), 400, (30, 30, 220, 255), -1)
    logo = cv2.imdecode(np.frombuffer(prepare_logo(cv2.imencode(".png", page)[1].tobytes()), np.uint8),
                        cv2.IMREAD_UNCHANGED)
    assert logo.shape[2] == 4 and max(logo.shape[:2]) == 512 and abs(logo.shape[0] - logo.shape[1]) <= 2
    assert logo[0, 0, 3] == 0 and logo[256, 256, 3] == 255  # still transparent around the disc
    white = np.full((400, 400, 3), 255, np.uint8)
    cv2.rectangle(white, (100, 150), (300, 250), (0, 0, 0), -1)
    trimmed = cv2.imdecode(np.frombuffer(prepare_logo(cv2.imencode(".jpg", white)[1].tobytes()), np.uint8),
                           cv2.IMREAD_UNCHANGED)
    assert trimmed.shape[:2] == (105, 205)  # the white margins are gone
    for data, why in ((b"not a picture", "isn't a picture"), (cv2.imencode(".png", np.full((50, 50), 255, np.uint8))[1]
                                                        .tobytes(), "blank"),
                      (cv2.imencode(".png", np.zeros((10, 10), np.uint8))[1].tobytes(), "too small"),
                      (cv2.imencode(".png", np.zeros((40, 900), np.uint8))[1].tobytes(), "long and thin"),
                      (b"x" * 10_000_001, "over 10 MB")):
        with pytest.raises(ValueError, match=why):
            prepare_logo(data)


def test_institute_details_are_checked_and_kept():
    inst = check(Institute("  Sunrise Academy ", website="sunrise.example", colour="#123abc"))
    assert inst.name == "Sunrise Academy" and from_json(to_json(inst)) == inst
    assert Institute("A", phone="01-555", email="a@b.np").contact() == "01-555  ·  a@b.np"
    for bad, why in ((Institute(""), "needs a name"), (Institute("A", colour="blue"), "colour"),
                     (Institute("A", motto="x" * 121), "motto"), (Institute("A", phone="1\n2"), "one line"),
                     (Institute("A", logo=b"junk"), "damaged")):
        with pytest.raises(ValueError, match=why):
            check(bad)
