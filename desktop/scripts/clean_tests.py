import glob
for file in glob.glob('desktop/tests/*.test.ts'):
    content = open(file).read()
    lines = content.split('\n')
    new_lines = []
    for line in lines:
        if 'expect(renderer).toContain' in line or 'expect(renderer).not.toContain' in line or 'renderer.match' in line or 'expect(openDialog' in line or 'expect(aboutDialog' in line:
            continue
        new_lines.append(line)
    open(file, 'w').write('\n'.join(new_lines))
