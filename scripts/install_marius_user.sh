#!/usr/bin/env bash
set -e

# Marius User-Level Installer
# This script creates a wrapper in ~/.local/bin/marius pointing to the repo

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="${HOME}/.local/bin"
TARGET="${BIN_DIR}/marius"

echo "Marius User Installer"
echo "---------------------"

# Create bin dir if it doesn't exist
if [ ! -d "${BIN_DIR}" ]; then
    echo "Creating ${BIN_DIR}..."
    mkdir -p "${BIN_DIR}"
fi

# Check for existing marius
if [ -e "${TARGET}" ]; then
    echo "Warning: ${TARGET} already exists."
    read -p "Overwrite with new wrapper? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled."
        exit 1
    fi
    rm "${TARGET}"
fi

# Create wrapper script
echo "Creating wrapper at ${TARGET}..."
cat <<EOF > "${TARGET}"
#!/usr/bin/env bash
set -e
REPO="${ROOT_DIR}"
cd "\$REPO"
exec "\$REPO/scripts/marius" "\$@"
EOF

chmod +x "${TARGET}"

echo "Installation complete."

# Path hint
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo
    echo "Hint: ${BIN_DIR} is not on your PATH."
    echo "Add this to your .bashrc or .zshrc:"
    echo '  export PATH="${HOME}/.local/bin:$PATH"'
fi

echo
echo "You can now run 'marius' from anywhere."
