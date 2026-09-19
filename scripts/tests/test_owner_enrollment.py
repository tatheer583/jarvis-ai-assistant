from Backend.Config import Config
from Backend.OwnerEnrollment import delete_pin, pin_configured, set_pin, verify_pin

def test_pin_is_hashed_and_verifiable(tmp_path):
    config = Config(tmp_path)
    set_pin(config, "4829")
    assert pin_configured(config)
    assert verify_pin(config, "4829")
    assert not verify_pin(config, "0000")
    assert "4829" not in (tmp_path / "owner-security" / "pin.json").read_text()
    assert delete_pin(config)
    assert not pin_configured(config)
