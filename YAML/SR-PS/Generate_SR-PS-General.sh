#!/bin/bash

python3 Combine.py -tf SR-PS-General-Template.yaml -af aliases-quads.yaml -hf header.yaml -ff footer.yaml > SR-PS-General_with_quads_From_template.yaml
cat <<EOT >> SR-PS-General_with_quads_From_template.yaml
- - {markup: Sextupoles, type: text, width: 13, wrap: clip}
EOT
python3 Combine.py -tf SR-PS-General-Template.yaml -af aliases-sextas.yaml -hf SR-PS-General_with_quads_From_template.yaml -ff footer.yaml > SR-PS-General.yaml
