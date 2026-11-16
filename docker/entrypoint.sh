#!/bin/sh
# Importa os workflows do repositório, publica (ativa) cada um e inicia o n8n.
set -e
n8n import:workflow --separate --input=/workflows
for id in $(n8n list:workflow --onlyId); do
  n8n publish:workflow --id="$id"
done
exec n8n start
