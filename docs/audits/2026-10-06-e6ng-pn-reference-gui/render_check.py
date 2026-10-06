"""보존된 실제 결과의 Tk 렌더링만 검사한다. 엔진 import/solve 금지."""
import hashlib
import json
import os
from pathlib import Path
import sys
import warnings

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

def prohibit_engine(event, args):
    if event == 'import' and args[0].split('.')[0] in {'devsim', 'viennaps', 'viennals'}:
        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')

sys.addaudithook(prohibit_engine)

def main():
    if os.name != 'nt' or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted':
        raise RuntimeError('REMOTE_WINDOWS_ONLY')
    source = Path(__file__).parent / 'raw/outputs/e6ng_out/result.json'
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert digest == '9b3212aad5eb00acd02fa1289442bbda0ee814b37078f5296f27b604d143705d'
    from tcad.characterization.pn_reference_view import show_result
    import tkinter as tk
    result = json.loads(source.read_text(encoding='utf-8'))
    out = ROOT / 'e6ng_render_out'
    out.mkdir(exist_ok=True)
    root = tk.Tk()
    root.withdraw()
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            window = show_result(root, result)
            root.update()
            canvas = window._pn_canvas
            canvas.draw()
            canvas.figure.savefig(out / 'pn_reference.png', dpi=120)
        missing = [str(w.message) for w in caught if 'Glyph' in str(w.message) and 'missing' in str(w.message)]
        assert not missing, missing
        assert len(canvas.figure.axes) == 4
        for axis in (canvas.figure.axes[0], canvas.figure.axes[2]):
            labels = [label.get_text() for label in axis.get_yticklabels()]
            assert labels and all('e' in label and '$' not in label for label in labels), labels
        report = {'pass': True, 'source_sha256': digest, 'missing_glyph_warnings': missing,
                  'engine_imports': 0, 'solves': 0, 'axes': 4}
        (out / 'render.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report))
    finally:
        root.destroy()

if __name__ == '__main__':
    main()
