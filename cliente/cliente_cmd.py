# -*- coding: utf-8 -*-
import requests
import json
import time
import threading
import uuid
import socket
import os
from typing import Dict, Any, Optional

# --- Configuração Inicial ---

# Variáveis de ambiente para o servidor ao qual o cliente se conecta
# No Docker Compose, SERVIDOR_HOST será o nome do serviço (ex: servidor_norte)
SERVIDOR_HOST_ENV = os.environ.get("SERVIDOR_HOST", "localhost")
SERVIDOR_PORTA_ENV = os.environ.get("SERVIDOR_PORTA", "8001") # Porta interna do contêiner (8000) ou porta mapeada (8001)

# Lista de servidores disponíveis (para simular a escolha)
SERVIDORES_DISPONIVEIS = {
    "Norte": "servidor_norte:8000",
    "Nordeste": "servidor_nordeste:8000",
    "Centro-Oeste": "servidor_centro_oeste:8000",
    "Sudeste": "servidor_sudeste:8000",
    "Sul": "servidor_sul:8000",
}

# --- Variáveis de Estado do Cliente ---

ID_JOGADOR: Optional[str] = None
NOME_JOGADOR: Optional[str] = None
INVENTARIO: Dict[str, Any] = {}
SERVIDOR_ATUAL_URL: str = f"http://{SERVIDOR_HOST_ENV}:{SERVIDOR_PORTA_ENV}"
SERVIDOR_ATUAL_NOME: str = SERVIDOR_HOST_ENV

# Configuração do Redis (para Pub/Sub)
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))

# --- Comunicação UDP para Latência ---

def medir_latencia_udp(servidor_host: str, servidor_porta_udp: int) -> float:
    """
    Mede a latência (ping) via UDP.
    Técnica: Envio de um pacote UDP com timestamp e cálculo do RTT (Round Trip Time)
    ao receber a resposta do servidor.
    """
    try:
        # Cria um socket UDP
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1.0) # Timeout de 1 segundo
        
        # O endereço é o host e a porta interna do contêiner (8000)
        endereco_servidor = (servidor_host, servidor_porta_udp)
        
        # Mensagem com timestamp
        timestamp_envio = time.time()
        mensagem = f"PING:{timestamp_envio}".encode('utf-8')
        
        # Envia a mensagem
        sock.sendto(mensagem, endereco_servidor)
        
        # Recebe a resposta
        dados, _ = sock.recvfrom(1024)
        timestamp_recebimento = time.time()
        
        # Calcula a latência
        latencia = (timestamp_recebimento - timestamp_envio) * 1000 # em milissegundos
        
        return latencia
        
    except socket.timeout:
        return -1.0 # Indica timeout
    except Exception as e:
        # Código -2.0 para erro geral de comunicação
        return -2.0 
    finally:
        sock.close()

# --- Comunicação com a API REST (Servidor) ---

def conectar_servidor(nome: str, url_servidor: str):
    """Conecta o jogador ao servidor e obtém o ID e inventário."""
    global ID_JOGADOR, NOME_JOGADOR, INVENTARIO, SERVIDOR_ATUAL_URL
    try:
        response = requests.post(f"{url_servidor}/jogador/entrar?nome_jogador={nome}")
        response.raise_for_status()
        dados = response.json()
        
        ID_JOGADOR = dados['jogador']['id_jogador']
        NOME_JOGADOR = dados['jogador']['nome']
        INVENTARIO = dados['inventario']
        SERVIDOR_ATUAL_URL = url_servidor
        
        print(f"\n[SUCESSO] Conectado como {NOME_JOGADOR} (ID: {ID_JOGADOR})!")
        print(f"Inventário inicial: {INVENTARIO['pacotes_disponiveis']} pacotes.")
        
        # Inicia a escuta de eventos
        threading.Thread(target=escutar_eventos_pubsub, daemon=True).start()
        
    except requests.exceptions.RequestException as e:
        print(f"\n[ERRO] Falha ao conectar ao servidor {url_servidor}: {e}")
        time.sleep(1)

def abrir_pacote():
    """Chama o endpoint para iniciar a abertura de pacote (2PC)."""
    global INVENTARIO, ID_JOGADOR
    
    if not ID_JOGADOR:
        print("[ERRO] Você precisa se conectar primeiro.")
        return
        
    if INVENTARIO.get('pacotes_disponiveis', 0) <= 0:
        print("[AVISO] Você não tem pacotes para abrir.")
        return
        
    print(f"\n[INFO] Tentando abrir pacote... (Iniciando 2PC distribuído)")
    try:
        response = requests.post(f"{SERVIDOR_ATUAL_URL}/pacote/abrir/{ID_JOGADOR}")
        response.raise_for_status()
        
        # A resposta do servidor já contém o resultado final (COMMIT)
        dados = response.json()
        INVENTARIO = dados['inventario_atualizado']
        
        print("\n" + "="*40)
        print("[SUCESSO] Pacote aberto e transação 2PC concluída.")
        print(f"Total de cartas no inventário: {len(INVENTARIO['cartas'])}")
        print("="*40 + "\n")
        
    except requests.exceptions.HTTPError as e:
        try:
            erro_detail = e.response.json().get('detail', str(e))
        except:
            erro_detail = str(e)
        print(f"\n[ERRO] Falha ao abrir pacote: {erro_detail}")
    except requests.exceptions.RequestException as e:
        print(f"\n[ERRO] Falha de comunicação com o servidor: {e}")

def ver_inventario():
    """Exibe o inventário local e mede a latência."""
    if not ID_JOGADOR:
        print("[ERRO] Você precisa se conectar primeiro.")
        return
        
    # Medir Latência
    # O SERVIDOR_ATUAL_URL é do tipo http://servico:porta.
    # O host é o nome do serviço (ex: servidor_norte) e a porta é a porta interna (8000).
    host_udp = SERVIDOR_ATUAL_URL.split('//')[1].split(':')[0].split(':')[0] # Garante que pega apenas o host
    porta_udp = int(SERVIDOR_ATUAL_URL.split(':')[-1])
    
    latencia = medir_latencia_udp(host_udp, porta_udp) 
    
    print(f"\n[LATÊNCIA] Servidor: {SERVIDOR_ATUAL_URL}")
    if latencia > 0:
        print(f"[PING UDP] {latencia:.2f} ms")
    else:
        print(f"[PING UDP] Falha ao medir ping UDP. Código: {latencia}")
        
    print("\n" + "="*40)
    print(f"INVENTÁRIO de {NOME_JOGADOR} (Pacotes: {INVENTARIO.get('pacotes_disponiveis', 0)})")
    print("="*40)
    
    if not INVENTARIO.get('cartas'):
        print("Nenhuma carta no inventário.")
        return
        
    for i, carta in enumerate(INVENTARIO['cartas']):
        print(f"[{i+1:02d}] ID: {carta['id_carta']} | {carta['nome']} ({carta['tipo'].capitalize()}) | Skin: {carta['skin']} | Raridade: {carta['raridade']}")
    print("="*40)

def trocar_cartas():
    """Simula o processo de troca de cartas."""
    if not ID_JOGADOR:
        print("[ERRO] Você precisa se conectar primeiro.")
        return
        
    ver_inventario()
    if len(INVENTARIO.get('cartas', [])) < 1:
        print("[AVISO] Você precisa de pelo menos uma carta para trocar.")
        return
        
    try:
        idx_carta_a = int(input("Digite o NÚMERO da sua carta para trocar: ")) - 1
        id_carta_a = INVENTARIO['cartas'][idx_carta_a]['id_carta']
        
        id_jogador_b = input("Digite o ID do jogador com quem você quer trocar: ")
        id_carta_b = input("Digite o ID da carta que você quer receber: ")
        
        print(f"\n[INFO] Tentando iniciar troca com {id_jogador_b}...")
        
        response = requests.post(
            f"{SERVIDOR_ATUAL_URL}/inventario/troca/{ID_JOGADOR}/{id_jogador_b}",
            params={"id_carta_a": id_carta_a, "id_carta_b": id_carta_b}
        )
        response.raise_for_status()
        
        print("\n[SUCESSO] Troca de cartas concluída via 2PC! Aguarde notificação Pub/Sub para atualização do inventário.")
        
    except IndexError:
        print("[ERRO] Número de carta inválido.")
    except ValueError:
        print("[ERRO] Entrada inválida. Use números.")
    except requests.exceptions.HTTPError as e:
        try:
            erro_detail = e.response.json().get('detail', str(e))
        except:
            erro_detail = str(e)
        print(f"\n[ERRO] Falha na troca: {erro_detail}")
    except requests.exceptions.RequestException as e:
        print(f"\n[ERRO] Falha de comunicação com o servidor: {e}")

def iniciar_partida():
    """Simula a busca por partida (pareamento)."""
    if not ID_JOGADOR:
        print("[ERRO] Você precisa se conectar primeiro.")
        return
        
    print("\n[INFO] Buscando partida 1v1 em ambiente distribuído...")
    # O cliente envia uma requisição para o servidor local
    try:
        response = requests.post(f"{SERVIDOR_ATUAL_URL}/pareamento/solicitar", json={
            "id_jogador_solicitante": ID_JOGADOR,
            "servidor_solicitante_url": SERVIDOR_ATUAL_URL,
            "tipo_jogo": "Pedra-Papel-Tesoura 1v1"
        })
        response.raise_for_status()
        
        dados = response.json()
        if dados['aceito']:
            print(f"[SUCESSO] Pareamento aceito. ID da Partida: {dados['id_partida']}")
            print("[INFO] Aguardando o início da partida via notificação Pub/Sub...")
        else:
            print(f"[AVISO] Pareamento não aceito: {dados['mensagem']}")
            
    except requests.exceptions.RequestException as e:
        print(f"\n[ERRO] Falha ao solicitar pareamento: {e}")

def escolher_servidor():
    """Permite ao usuário escolher o servidor ao qual se conectar."""
    global SERVIDOR_ATUAL_URL, SERVIDOR_ATUAL_NOME, ID_JOGADOR, NOME_JOGADOR, INVENTARIO # CORREÇÃO: Declaração global no início
    
    print("\n" + "="*40)
    print("ESCOLHA DO SERVIDOR REGIONAL")
    print("="*40)
    
    opcoes = list(SERVIDORES_DISPONIVEIS.keys())
    for i, nome in enumerate(opcoes):
        print(f"{i+1}. {nome} ({SERVIDORES_DISPONIVEIS[nome]})")
    
    print("="*40)
    
    try:
        escolha = int(input("Escolha o número do servidor: "))
        if 1 <= escolha <= len(opcoes):
            nome_servidor = opcoes[escolha - 1]
            host_porta = SERVIDORES_DISPONIVEIS[nome_servidor]
            
            SERVIDOR_ATUAL_URL = f"http://{host_porta}"
            SERVIDOR_ATUAL_NOME = nome_servidor
            
            print(f"\n[INFO] Servidor selecionado: {SERVIDOR_ATUAL_NOME} ({SERVIDOR_ATUAL_URL})")
            
            # Se já estiver logado, desconecta
            if ID_JOGADOR:
                print("[AVISO] Desconectando o jogador atual. Por favor, entre novamente.")
                ID_JOGADOR = None
                NOME_JOGADOR = None
                INVENTARIO = {}
                
            return True
        else:
            print("[AVISO] Opção inválida.")
            return False
    except ValueError:
        print("[ERRO] Entrada inválida. Use números.")
        return False

# --- Escuta de Eventos (Pub/Sub) ---

def escutar_eventos_pubsub():
    """
    Escuta por eventos no Redis Pub/Sub em uma thread separada.
    """
    import redis
    try:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        p = r.pubsub()
        
        # Canais a escutar
        canais = ["eventos_gerais", f"notificacoes_jogador_{ID_JOGADOR}"]
        p.subscribe(*canais)
        
        print(f"[PUBSUB] Escutando eventos nos canais: {', '.join(canais)}")
        
        for mensagem in p.listen():
            if mensagem['type'] == 'message':
                try:
                    dados = json.loads(mensagem['data'])
                    tipo = dados.get('tipo', 'desconhecido')
                    
                    if tipo == 'pacote_aberto':
                        print("\n" + "="*40)
                        print(f"[NOTIFICAÇÃO] Pacote Aberto: {dados['status'].upper()}")
                        if dados['status'] == 'sucesso':
                            print(f"Novas Cartas: {len(dados['cartas_obtidas'])}")
                        print("="*40 + "\n")
                        
                    elif tipo == 'troca_cartas':
                        print("\n" + "="*40)
                        print(f"[NOTIFICAÇÃO] Troca de Cartas: {dados['status'].upper()}")
                        print("="*40 + "\n")
                        
                    elif tipo == 'pareamento_aceito':
                        print("\n" + "="*40)
                        print(f"[NOTIFICAÇÃO] Partida Encontrada! ID: {dados['id_partida']}")
                        print(f"Servidores: {dados['servidor1']} vs {dados['servidor2']}")
                        print("="*40 + "\n")
                        
                    elif tipo == 'jogada':
                        print(f"\n[NOTIFICAÇÃO] Jogada na Partida {dados['id_partida']}: {dados['id_jogador']} jogou {dados['jogada']}")
                        
                    else:
                        print(f"\n[PUBSUB] Mensagem recebida no canal {mensagem['channel']}: {dados}")
                        
                except json.JSONDecodeError:
                    print(f"[PUBSUB] Erro ao decodificar JSON: {mensagem['data']}")
                except Exception as e:
                    print(f"[PUBSUB] Erro no processamento da mensagem: {e}")
                    
    except redis.exceptions.ConnectionError:
        print("\n[ERRO CRÍTICO] Falha ao conectar ao Redis para Pub/Sub. Eventos em tempo real desativados.")
    except Exception as e:
        print(f"\n[ERRO CRÍTICO] Erro na thread Pub/Sub: {e}")

# --- Menu Principal ---

def menu_principal():
    """Exibe o menu e processa a escolha do usuário."""
    
    # Seleção inicial do servidor
    if not SERVIDOR_ATUAL_URL.startswith("http://servidor_"):
        escolher_servidor()

    if not ID_JOGADOR:
        nome = input(f"Digite seu nome para conectar ao {SERVIDOR_ATUAL_NOME}: ")
        conectar_servidor(nome, SERVIDOR_ATUAL_URL)
        if not ID_JOGADOR:
            return
            
    while True:
        print("\n" + "="*40)
        print(f"MENU PRINCIPAL - {NOME_JOGADOR} @ {SERVIDOR_ATUAL_NOME}")
        print("="*40)
        print("1. Iniciar Partida (1v1)")
        print("2. Abrir Pacotes (2PC)")
        print("3. Ver Inventário e Ping")
        print("4. Trocar Cartas (2PC)")
        print("5. Mudar Servidor")
        print("6. Sair")
        print("="*40)
        
        escolha = input("Escolha uma opção: ")
        
        if escolha == '1':
            iniciar_partida()
        elif escolha == '2':
            abrir_pacote()
        elif escolha == '3':
            ver_inventario()
        elif escolha == '4':
            trocar_cartas()
        elif escolha == '5':
            escolher_servidor()
            # Reinicia o loop do menu, pedindo login novamente se o servidor mudou
            if not ID_JOGADOR:
                nome = input(f"Digite seu nome para conectar ao {SERVIDOR_ATUAL_NOME}: ")
                conectar_servidor(nome, SERVIDOR_ATUAL_URL)
        elif escolha == '6':
            print("Saindo...")
            break
        else:
            print("[AVISO] Opção inválida. Tente novamente.")

if __name__ == "__main__":
    menu_principal()
