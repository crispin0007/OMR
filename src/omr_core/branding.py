"""An institute's name, logo and details, printed on its sheets, scorecards and exports."""

import re
from dataclasses import asdict, dataclass, fields

import cv2
import numpy as np

COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LOGO_MAX_FILE = 10_000_000  # bytes of the picked file
LOGO_MIN_PX = 32
LOGO_MAX_PX = 512  # the longer side once trimmed; sharp at the 30 mm a scorecard prints it
LIMITS = {"name": 120, "address": 200, "phone": 60, "email": 120, "website": 120, "motto": 120,
          "signer_name": 80, "signer_title": 80, "footer": 200}


@dataclass
class Institute:
    name: str
    address: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    motto: str = ""
    colour: str = "#1565c0"
    signer_name: str = ""  # who signs the scorecards, e.g. the principal
    signer_title: str = ""
    footer: str = ""  # a line at the foot of every scorecard
    logo: bytes = b""  # PNG from `prepare_logo`, or nothing

    def contact(self) -> str:
        """Phone, email and website on one line."""
        return "  ·  ".join(x for x in (self.phone, self.email, self.website) if x)


def check(inst: Institute) -> Institute:
    """The institute with its text trimmed. Raises ValueError naming what can't be used."""
    values = {f.name: getattr(inst, f.name).strip() if isinstance(getattr(inst, f.name), str)
              else getattr(inst, f.name) for f in fields(inst)}
    if not values["name"]:
        raise ValueError("the institute needs a name")
    for key, most in LIMITS.items():
        if len(values[key]) > most:
            raise ValueError(f"{key.replace('_', ' ')} can be up to {most} characters")
        if "\n" in values[key] and key != "address":
            raise ValueError(f"{key.replace('_', ' ')} must be one line")
    if not COLOUR.match(values["colour"]):
        raise ValueError("the colour must look like #1565c0")
    if values["email"] and not EMAIL.match(values["email"]):
        raise ValueError(f"{values['email']} doesn't look like an email address")
    if values["logo"] and cv2.imdecode(np.frombuffer(values["logo"], np.uint8), cv2.IMREAD_UNCHANGED) is None:
        raise ValueError("the logo is damaged")
    return Institute(**values)


def prepare_logo(data: bytes) -> bytes:
    """A picked logo file as PNG: empty margins trimmed, at most 512 px, transparency kept.
    Raises ValueError when it isn't a usable picture."""
    if len(data) > LOGO_MAX_FILE:
        raise ValueError("the logo file is over 10 MB; pick a smaller picture")
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError("the logo isn't a picture this app can open (use PNG or JPEG)")
    if image.dtype != np.uint8:
        image = cv2.convertScaleAbs(image, alpha=255 / max(1, int(image.max())))
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGRA)
    elif image.shape[2] == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
    # Trim margins that are transparent or near-white, so the logo fills the space it is given.
    ink = (image[:, :, 3] > 16) & (image[:, :, :3].min(axis=2) < 245)
    ys, xs = np.nonzero(ink)
    if len(xs) == 0:
        raise ValueError("the logo is blank")
    pad = 2
    image = image[max(0, ys.min() - pad):ys.max() + 1 + pad, max(0, xs.min() - pad):xs.max() + 1 + pad]
    high, wide = image.shape[:2]
    if max(high, wide) < LOGO_MIN_PX:
        raise ValueError(f"the logo is too small ({wide}×{high} pixels); pick one at least 128 pixels wide")
    if max(high, wide) / min(high, wide) > 8:
        raise ValueError("the logo is too long and thin to print; use the emblem, or a picture at most 8 times "
                         "as wide as it is high")
    scale = min(1.0, LOGO_MAX_PX / max(image.shape[:2]))
    if scale < 1:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return cv2.imencode(".png", image)[1].tobytes()


def logo_on_white(logo: bytes) -> bytes:
    """The logo as JPEG on white paper, for places without transparency (the printed sheet)."""
    image = cv2.imdecode(np.frombuffer(logo, np.uint8), cv2.IMREAD_UNCHANGED)
    alpha = image[:, :, 3:] / 255.0
    flat = (image[:, :, :3] * alpha + 255 * (1 - alpha)).astype(np.uint8)
    return cv2.imencode(".jpg", flat, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()


def to_json(inst: Institute) -> dict:
    """Everything but the logo, which is kept apart."""
    d = asdict(inst)
    d.pop("logo")
    return d


def from_json(d: dict, logo: bytes = b"") -> Institute:
    """Raises ValueError for anything that isn't an institute."""
    try:
        return check(Institute(**{f.name: str(d.get(f.name, "")) for f in fields(Institute) if f.name != "logo"}
                               | {"colour": str(d.get("colour") or Institute.colour), "logo": logo or b""}))
    except TypeError as e:
        raise ValueError(f"not an institute ({e})") from e
