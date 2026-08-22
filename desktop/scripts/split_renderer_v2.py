import re
from pathlib import Path
import subprocess

# get original file
content = subprocess.check_output(['git', 'show', 'HEAD:desktop/src/renderer/index.ts']).decode('utf-8')

def extract_section(marker1, marker2=None):
    if marker2:
        match = re.search(f"{marker1}(.*?){marker2}", content, re.DOTALL)
    else:
        match = re.search(f"{marker1}(.*)", content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""

connected_ais = extract_section("// ---------------------------------------------------------------------------\n// CONNECTED AIS & ADVANCED SCREENS", "// ---------------------------------------------------------------------------\n// ATTENTION RESOLUTION")
terminals = extract_section("// ---------------------------------------------------------------------------\n// TERMINALS & PLATFORMS", "// ---------------------------------------------------------------------------\n// INITIALIZATION")

Path('desktop/src/renderer/modules/connected-ais.ts').write_text("import { $, ui, escapeHtml, notice } from './state';\nimport { selectNav } from './nav';\nimport { providerBounds } from './util';\nimport type { WebPlatform, PlatformPreset } from '../../shared/types';\n\n" + connected_ais)
Path('desktop/src/renderer/modules/terminals.ts').write_text("import { Terminal } from '@xterm/xterm';\nimport { FitAddon } from '@xterm/addon-fit';\nimport { $, ui, type UiTerminal } from './state';\nimport type { TerminalMetadata } from '../../shared/types';\n\n" + terminals)

