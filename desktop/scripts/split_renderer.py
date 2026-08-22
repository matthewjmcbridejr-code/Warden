import re
from pathlib import Path

content = Path('desktop/src/renderer/index.ts').read_text()

def extract_section(marker1, marker2=None):
    if marker2:
        match = re.search(f"{marker1}(.*?){marker2}", content, re.DOTALL)
    else:
        match = re.search(f"{marker1}(.*)", content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""

home_code = extract_section("// ---------------------------------------------------------------------------\n// HOME SCREEN\n// ---------------------------------------------------------------------------", "// ---------------------------------------------------------------------------\n// NEEDS YOU")
needs_you = extract_section("// ---------------------------------------------------------------------------\n// NEEDS YOU", "// ---------------------------------------------------------------------------\n// MISSION WORKSPACE")
mission = extract_section("// ---------------------------------------------------------------------------\n// MISSION WORKSPACE", "// ---------------------------------------------------------------------------\n// MISSION CREATION")
mission_start = extract_section("// ---------------------------------------------------------------------------\n// MISSION CREATION", "// ---------------------------------------------------------------------------\n// TERMINALS")
terminals = extract_section("// ---------------------------------------------------------------------------\n// TERMINALS & PLATFORMS\n// ---------------------------------------------------------------------------", "// ---------------------------------------------------------------------------\n// CONNECTED AIS")
connected_ais = extract_section("// ---------------------------------------------------------------------------\n// CONNECTED AIS", "// ---------------------------------------------------------------------------\n// ADVANCED")
advanced = extract_section("// ---------------------------------------------------------------------------\n// ADVANCED", "// ---------------------------------------------------------------------------\n// INIT")

Path('desktop/src/renderer/modules/home.ts').write_text("import { $, ui, escapeHtml } from './state';\nimport { selectNav } from './nav';\nimport { MISSION_TEMPLATES } from '../simple-build';\nimport { startMissionFromPrompt } from './mission';\n\n" + home_code)
Path('desktop/src/renderer/modules/mission.ts').write_text("import { $, ui, escapeHtml, notice, type ActiveMissionData } from './state';\nimport { selectNav, selectContextTab, renderProjectsTree } from './nav';\nimport { renderHomeScreen } from './home';\nimport { updateNeedsYouCount } from './needs-you';\n\n" + mission + "\n\n" + mission_start)
Path('desktop/src/renderer/modules/terminals.ts').write_text("import { Terminal } from '@xterm/xterm';\nimport { FitAddon } from '@xterm/addon-fit';\nimport { $, ui, type UiTerminal } from './state';\nimport type { TerminalMetadata } from '../../shared/types';\n\n" + terminals)
Path('desktop/src/renderer/modules/connected-ais.ts').write_text("import { $, ui, escapeHtml, notice } from './state';\nimport { selectNav } from './nav';\nimport { providerBounds } from './util';\nimport type { WebPlatform, PlatformPreset } from '../../shared/types';\n\n" + connected_ais)
Path('desktop/src/renderer/modules/advanced.ts').write_text("import { $, ui, escapeHtml, notice } from './state';\n\n" + advanced)
