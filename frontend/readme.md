Setting up:
1. create your virtual environment with uv venv
2. activate your .venv as usual
3. run uv sync
4. run [important] in the root folder pre-commit install
5. test it by running pre-commit run --all-files


To run the code use the following command:
uv run streamlit run main.py --server.port 5000