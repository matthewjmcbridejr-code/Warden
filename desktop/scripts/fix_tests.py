import glob
for file in glob.glob('desktop/tests/*.test.ts'):
    content = open(file).read()
    content = content.replace(
        "const renderer = readFileSync(join(process.cwd(), 'src/renderer/index.ts'), 'utf8');",
        "import { readdirSync } from 'node:fs';\nconst renderer = readdirSync(join(process.cwd(), 'src/renderer/modules')).map(f => readFileSync(join(process.cwd(), 'src/renderer/modules', f), 'utf8')).join('\\n') + '\\n' + readFileSync(join(process.cwd(), 'src/renderer/index.ts'), 'utf8');"
    )
    open(file, 'w').write(content)
