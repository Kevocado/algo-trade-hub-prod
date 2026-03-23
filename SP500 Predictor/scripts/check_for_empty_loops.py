import sys

def check_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    problems = []
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith('for ') or stripped.startswith('for') and stripped.rstrip().endswith(':'):
            # look ahead for the next non-empty line
            j = i + 1
            while j < len(lines) and lines[j].strip() == '':
                j += 1
            if j >= len(lines):
                problems.append((i+1, 'for with no following block'))
                continue
            next_line = lines[j]
            # If next line is comment only, also a problem
            if next_line.lstrip().startswith('#'):
                problems.append((i+1, 'for followed only by comment/blank'))
                continue
            # Check indentation: next line should be more indented than the for line
            indent_for = len(line) - len(line.lstrip())
            indent_next = len(next_line) - len(next_line.lstrip())
            if indent_next <= indent_for:
                problems.append((i+1, f'following line at {j+1} is not indented (indent_for={indent_for}, indent_next={indent_next})'))

    if problems:
        print(f"Found {len(problems)} potential problems in {path}:")
        for ln, msg in problems:
            print(f"  Line {ln}: {msg}")
        return 1
    else:
        print(f"No empty-for problems detected in {path}.")
        return 0

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python check_for_empty_loops.py <file>")
        sys.exit(2)
    sys.exit(check_file(sys.argv[1]))
