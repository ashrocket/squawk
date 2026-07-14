import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("wake", pathlib.Path(__file__).resolve().parent.parent / "wake.py")
wake = importlib.util.module_from_spec(spec)

def test_crossed_threshold_true():
    spec.loader.exec_module(wake)
    assert wake.crossed({"hey_jarvis": 0.81}, 0.5) is True

def test_below_threshold_false():
    spec.loader.exec_module(wake)
    assert wake.crossed({"hey_jarvis": 0.10}, 0.5) is False

def test_empty_scores_false():
    spec.loader.exec_module(wake)
    assert wake.crossed({}, 0.5) is False
