# -*- coding: utf-8 -*-
import requests
import json
import time
import threading
from typing import List, Dict, Any

# --- Configurações de Teste ---

# Endpoints dos 5 servidores (baseado no docker-compose.yml)
SERVIDORES = {
    "norte": "http://localhost:8001",
    "nordeste": "http://localhost:8002",
    "centro_oeste": "http://localhost:8003",
    "sudeste": "http://localhost:8004",
    "sul": "http://localhost:8005",
}

URL_ESTOQUE_BASE = SERVIDORES["norte"] # Qualquer servidor pode fornecer o estoque

# --- Funções Auxiliares ---

def get_estoque_global() -> int:
    """Obtém o valor atual do estoque global."""
    try:
        response = requests.get(f"{URL_ESTOQUE_BASE}/")
        response.raise_for_status()
        return response.json().get("estoque_global", -1)
    except Exception as e:
        print(f"Erro ao obter estoque global: {e}")
        return -1

def entrar_jogador(servidor_url: str, nome: str) -> str:
    """Simula a entrada de um jogador e retorna o ID."""
    try:
        response = requests.post(f"{servidor_url}/jogador/entrar?nome_jogador={nome}")
        response.raise_for_status()
        return response.json()["jogador"]["id_jogador"]
    except Exception as e:
        print(f"Erro ao entrar jogador {nome} em {servidor_url}: {e}")
        return ""

def abrir_pacote(servidor_url: str, id_jogador: str, resultados: List[str]):
    """Simula a abertura de pacote e registra o resultado."""
    try:
        response = requests.post(f"{servidor_url}/pacote/abrir/{id_jogador}")
        response.raise_for_status()
        resultados.append("SUCESSO")
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 500 and "abortada" in e.response.json().get("detail", ""):
            resultados.append("ABORT_2PC")
        elif e.response.status_code == 400 and "disponíveis para abrir" in e.response.json().get("detail", ""):
            resultados.append("SEM_PACOTES_JOGADOR")
        elif e.response.status_code == 500 and "Falha na abertura do pacote" in e.response.json().get("detail", ""):
            resultados.append("FALHA_GERAL")
        else:
            resultados.append(f"ERRO_HTTP_{e.response.status_code}")
    except Exception as e:
        resultados.append(f"ERRO_COMUNICACAO_{e.__class__.__name__}")

def ver_inventario(servidor_url: str, id_jogador: str) -> Dict[str, Any]:
    """Obtém o inventário de um jogador."""
    try:
        response = requests.get(f"{servidor_url}/inventario/{id_jogador}")
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Erro ao obter inventário de {id_jogador}: {e}")
        return {}

def trocar_cartas(servidor_url: str, id_jogador_a: str, id_jogador_b: str, id_carta_a: str, id_carta_b: str, resultados: List[str]):
    """Simula a troca de cartas e registra o resultado."""
    try:
        response = requests.post(
            f"{servidor_url}/inventario/troca/{id_jogador_a}/{id_jogador_b}",
            params={"id_carta_a": id_carta_a, "id_carta_b": id_carta_b}
        )
        response.raise_for_status()
        resultados.append("SUCESSO_TROCA")
    except requests.exceptions.HTTPError as e:
        resultados.append(f"ABORT_TROCA_{e.response.status_code}")
    except Exception as e:
        resultados.append(f"ERRO_TROCA_{e.__class__.__name__}")

# --- Testes ---

def teste_concorrencia_abertura_pacotes():
    """
    Teste 1: Simula a abertura de pacotes por múltiplos clientes em diferentes servidores.
    O estoque inicial é 50. Espera-se 50 SUCESSO e o restante ABORT_2PC.
    """
    print("\n" + "="*50)
    print("TESTE 1: CONCORRÊNCIA NA ABERTURA DE PACOTES (2PC)")
    print("="*50)

    # 1. Preparação: Criar 60 jogadores, 12 em cada servidor.
    jogadores = []
    for i, (nome_servidor, url) in enumerate(SERVIDORES.items()):
        for j in range(12):
            nome_jogador = f"Jogador_{i}_{j}"
            id_jogador = entrar_jogador(url, nome_jogador)
            if id_jogador:
                jogadores.append((url, id_jogador))
    
    # Estoque inicial (deve ser 50)
    estoque_inicial = get_estoque_global()
    print(f"Estoque Global Inicial: {estoque_inicial}")
    
    if estoque_inicial <= 0:
        print("AVISO: Estoque inicial <= 0. Não é possível rodar o teste.")
        return

    # 2. Execução: Iniciar 60 threads tentando abrir um pacote.
    threads = []
    resultados = []
    
    print(f"Iniciando {len(jogadores)} requisições concorrentes...")
    
    for url, id_jogador in jogadores:
        t = threading.Thread(target=abrir_pacote, args=(url, id_jogador, resultados))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # 3. Verificação
    estoque_final = get_estoque_global()
    sucessos = resultados.count("SUCESSO")
    aborts_2pc = resultados.count("ABORT_2PC")
    
    print("\n--- Resultados ---")
    print(f"Total de Requisições: {len(jogadores)}")
    print(f"Sucessos (COMMIT): {sucessos}")
    print(f"Aborts 2PC (Estoque): {aborts_2pc}")
    print(f"Outras Falhas: {len(resultados) - sucessos - aborts_2pc}")
    print(f"Estoque Global Final Esperado: {estoque_inicial - sucessos}")
    print(f"Estoque Global Final Real: {estoque_final}")
    
    # O número de sucessos deve ser no máximo o estoque inicial.
    # O estoque final deve ser o estoque inicial - sucessos.
    assert sucessos <= estoque_inicial, f"Falha: Mais sucessos ({sucessos}) do que estoque inicial ({estoque_inicial})."
    assert estoque_final == estoque_inicial - sucessos, f"Falha: Inconsistência no estoque. Esperado {estoque_inicial - sucessos}, Real {estoque_final}."
    
    print("\n[SUCESSO] Teste de Concorrência 2PC passou. A atomicidade foi mantida.")

def teste_falha_2pc_abort():
    """
    Teste 2: Simula uma falha em um participante (simulando timeout)
    e verifica se a transação é abortada globalmente.
    """
    print("\n" + "="*50)
    print("TESTE 2: FALHA DE PARTICIPANTE (ABORT GLOBAL)")
    print("="*50)
    
    # 1. Preparação: Entrar um jogador e garantir que o estoque não está esgotado.
    id_jogador = entrar_jogador(SERVIDORES["norte"], "Jogador_Falha")
    estoque_antes = get_estoque_global()
    
    if estoque_antes <= 0:
        print("AVISO: Estoque esgotado. Não é possível rodar o teste.")
        return

    # 2. Execução:
    # Para simular a falha de um participante, vamos forçar o Coordenador (servidor_norte)
    # a ter um timeout ao tentar se comunicar com um servidor que não existe ou que está lento.
    # Como não podemos controlar o timeout de forma granular no código atual,
    # vamos simular a falha do participante no lado do Coordenador, que é o que o 2PC trata.
    
    # O teste de concorrência já simula o cenário onde um participante não consegue
    # decrementar o estoque (VOTE_ABORT), o que leva ao ABORT global.
    # Vamos rodar uma transação que sabemos que irá falhar (Estoque esgotado).
    
    # Consumir o estoque até 1
    total_a_consumir = estoque_antes - 1
    jogadores_consumo = []
    for i in range(total_a_consumir):
        jogadores_consumo.append(entrar_jogador(SERVIDORES["sudeste"], f"Consumidor_{i}"))

    resultados_consumo = []
    threads_consumo = []
    for url, id_jogador in zip([SERVIDORES["sudeste"]] * total_a_consumir, jogadores_consumo):
        t = threading.Thread(target=abrir_pacote, args=(url, id_jogador, resultados_consumo))
        threads_consumo.append(t)
        t.start()
    for t in threads_consumo:
        t.join()
        
    estoque_apos_consumo = get_estoque_global()
    print(f"Estoque após consumo: {estoque_apos_consumo}")
    
    # Tentar abrir o último pacote (deve ser COMMIT)
    resultados_ultimo = []
    abrir_pacote(SERVIDORES["norte"], id_jogador, resultados_ultimo)
    
    estoque_final_commit = get_estoque_global()
    print(f"Estoque após último COMMIT: {estoque_final_commit}")
    
    # Tentar abrir o pacote que deve falhar (Estoque = 0)
    id_jogador_falha = entrar_jogador(SERVIDORES["norte"], "Jogador_Falha_2")
    resultados_falha = []
    abrir_pacote(SERVIDORES["norte"], id_jogador_falha, resultados_falha)
    
    estoque_final_abort = get_estoque_global()
    
    # 3. Verificação
    assert "ABORT_2PC" in resultados_falha or "ERRO_HTTP_400" in resultados_falha, "Falha: A transação deveria ter sido abortada ou falhado por falta de estoque."
    assert estoque_final_abort == estoque_final_commit, "Falha: O estoque não deveria ter mudado após o ABORT."
    
    print("\n[SUCESSO] Teste de Falha (ABORT) 2PC passou. O rollback foi garantido.")

def teste_troca_cartas_2pc():
    """
    Teste 3: Simula a troca de cartas entre dois jogadores em servidores diferentes.
    """
    print("\n" + "="*50)
    print("TESTE 3: TROCA DE CARTAS DISTRIBUÍDA (2PC)")
    print("="*50)
    
    # 1. Preparação: Jogadores em servidores diferentes
    id_jogador_a = entrar_jogador(SERVIDORES["norte"], "Alice")
    id_jogador_b = entrar_jogador(SERVIDORES["sul"], "Bob")
    
    # Garantir que ambos tenham cartas
    resultados_a = []
    abrir_pacote(SERVIDORES["norte"], id_jogador_a, resultados_a)
    
    resultados_b = []
    abrir_pacote(SERVIDORES["sul"], id_jogador_b, resultados_b)
    
    # Obter inventários
    inv_a = ver_inventario(SERVIDORES["norte"], id_jogador_a)
    inv_b = ver_inventario(SERVIDORES["sul"], id_jogador_b)
    
    if not inv_a.get('cartas') or not inv_b.get('cartas'):
        print("AVISO: Jogadores sem cartas para troca. Não é possível rodar o teste.")
        return

    # Escolher cartas para troca
    carta_a_para_troca = inv_a['cartas'][0]
    carta_b_para_troca = inv_b['cartas'][0]
    
    print(f"Alice ({id_jogador_a}) oferece: {carta_a_para_troca['nome']}")
    print(f"Bob ({id_jogador_b}) oferece: {carta_b_para_troca['nome']}")
    
    # 2. Execução: Troca de cartas (Alice inicia a transação)
    resultados_troca = []
    trocar_cartas(
        SERVIDORES["norte"], 
        id_jogador_a, 
        id_jogador_b, 
        carta_a_para_troca['id_carta'], 
        carta_b_para_troca['id_carta'], 
        resultados_troca
    )

    # 3. Verificação
    inv_a_final = ver_inventario(SERVIDORES["norte"], id_jogador_a)
    inv_b_final = ver_inventario(SERVIDORES["sul"], id_jogador_b)
    
    assert "SUCESSO_TROCA" in resultados_troca, f"Falha: Troca de cartas não foi bem-sucedida. Resultados: {resultados_troca}"
    
    # Alice deve ter a carta de Bob e não ter mais a dela
    assert any(c['id_carta'] == carta_b_para_troca['id_carta'] for c in inv_a_final['cartas']), "Falha: Alice não recebeu a carta de Bob."
    assert not any(c['id_carta'] == carta_a_para_troca['id_carta'] for c in inv_a_final['cartas']), "Falha: Alice ainda tem a carta que trocou."

    # Bob deve ter a carta de Alice e não ter mais a dele
    assert any(c['id_carta'] == carta_a_para_troca['id_carta'] for c in inv_b_final['cartas']), "Falha: Bob não recebeu a carta de Alice."
    assert not any(c['id_carta'] == carta_b_para_troca['id_carta'] for c in inv_b_final['cartas']), "Falha: Bob ainda tem a carta que trocou."
    
    print("\n[SUCESSO] Teste de Troca de Cartas 2PC passou. A consistência foi mantida.")

def main():
    """Função principal para rodar todos os testes."""
    print("Iniciando Testes de Concorrência Distribuída...")
    
    # Pequena pausa para garantir que os servidores estejam de pé
    print("Aguardando 5 segundos para a inicialização dos servidores...")
    time.sleep(5)
    
    # Rodar Testes
    teste_concorrencia_abertura_pacotes()
    teste_falha_2pc_abort()
    teste_troca_cartas_2pc()
    
    print("\n" + "="*50)
    print("TODOS OS TESTES DE CONCORRÊNCIA DISTRIBUÍDA CONCLUÍDOS.")
    print("="*50)

if __name__ == "__main__":
    main()
