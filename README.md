# QA Pylinac

Interface local/web para executar analises de Winston-Lutz e Picket Fence com pylinac.

## Como rodar no servidor/local

```powershell
python -m pip install -r requirements.txt
streamlit run app.py
```

Depois abra o endereco mostrado pelo Streamlit no navegador.

Para manter rodando em um servidor interno, execute o mesmo comando no servidor:

```powershell
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

Na rede local, acesse pelo IP do servidor, por exemplo:

```text
http://IP_DO_SERVIDOR:8501
```

## Fluxo

1. Selecione a aba da analise: **Winston-Lutz** ou **Picket Fence**.
2. Na aba **Winston-Lutz**, selecione o phantom usado: **WL Cube** ou **MultiMet**.
3. Envie os DICOMs ou um ZIP com as imagens.
4. Ajuste os parametros da analise.
5. Execute a analise e baixe o PDF.

## Diferenca entre as analises

- **WL Cube** usa `pylinac.WinstonLutz`, indicado para Winston-Lutz convencional com um unico alvo/BB. A tela ja inclui o mapeamento padrao dos campos A1-A13 para gantry, colimador e mesa.
- **MultiMet** usa `pylinac.WinstonLutzMultiTargetMultiField`, indicado para arranjos com multiplos alvos/campos. A tela ja inclui o mapeamento padrao dos campos M1-M10 para gantry, colimador e mesa, e usa o arranjo convencional `BBArrangement.SNC_MULTIMET` da biblioteca do pylinac.
- **Picket Fence** usa `pylinac.PicketFence`, indicado para avaliar o posicionamento das laminas do MLC. A tela aceita uma imagem unica ou multiplas imagens combinadas.

## Publicar em site

O caminho mais simples e manter o codigo no GitHub e publicar pelo Streamlit Community Cloud.

1. Crie um repositorio no GitHub.
2. Suba estes arquivos: `app.py`, `requirements.txt`, `runtime.txt`, `README.md` e a pasta `.streamlit`.
3. Entre em https://share.streamlit.io/.
4. Clique em **New app**.
5. Selecione o repositorio.
6. Em **Main file path**, use `app.py`.
7. Clique em **Deploy**.

O Streamlit Cloud vai gerar um link publico para acessar de qualquer lugar.

## Observacoes de seguranca

O app salva os uploads apenas em pasta temporaria durante a analise. Mesmo assim, nao suba imagens DICOM de exemplo para o GitHub. Use o GitHub apenas para o codigo.
