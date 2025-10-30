# -*- coding: utf-8 -*-
from fastapi import FastAPI, HTTPException
from typing import List, Dict, Optional
import os
import time
import socket
import threading

from modelos import (
    Jogador, Inventario, EstoqueGlobal, Transacao2PC, Voto2PC, Resultado2PC,
    PareamentoSolicitacao, PareamentoResposta, Partida, DetalhesTroca
)
from servico_coordenacao import ServicoCoordenacao
from servico_2pc import Servico2PC, simular_abertura_pacote, SERVIDORES_JOGO
from servico_pubsub import ServicoPubSub, CANAL_EVENTOS_GERAIS, CANAL_NOTIFICACOES_JOGADOR

# --- Configuração Inicial ---

# O nome do servidor será lido de uma variável de ambiente (definida no Docker)
NOME_SERVIDOR = os.environ.get("NOME_SERVIDOR", "servidor_teste")
PORTA_SERVIDOR = int(os.environ.get("PORTA_SERVIDOR", 8000))
URL_LOCAL = f"http://{NOME_SERVIDOR}:{PORTA_SERVIDOR}"

app = FastAPI(
    title=f"Servidor de Jogo - {NOME_SERVIDOR}",
    description="API REST para comunicação Servidor-Servidor e Cliente-Servidor."
)

# Inicializa os serviços
servico_coordenacao = ServicoCoordenacao()
servico_2pc = Servico2PC(url_local=URL_LOCAL, servico_coordenacao=servico_coordenacao)
servico_pubsub = ServicoPubSub()

# --- Serviço UDP para Latência ---

def udp_listener():
    """
    Escuta por pacotes UDP na porta do servidor para responder ao ping de latência.
    Técnica: Uso de thread separada para não bloquear o servidor HTTP (FastAPI).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # O servidor deve escutar em 0.0.0.0 para aceitar conexões de qualquer IP
    try:
        sock.bind(("0.0.0.0", PORTA_SERVIDOR))
        print(f"[{NOME_SERVIDOR}] Listener UDP iniciado na porta {PORTA_SERVIDOR}")
        while True:
            # Recebe a mensagem (PING:timestamp)
            data, addr = sock.recvfrom(1024)
            # Responde imediatamente com a mesma mensagem
            sock.sendto(data, addr)
    except Exception as e:
        print(f"[{NOME_SERVIDOR}] Erro no listener UDP: {e}")
    finally:
        sock.close()

# Inicia o listener UDP em uma thread separada
threading.Thread(target=udp_listener, daemon=True).start()

# --- Funções de Callback para Eventos Internos (Servidor-Servidor) ---

def handle_evento_geral(evento: Dict):
    """Lida com eventos gerais, como atualização do estoque global."""
    print(f"[{NOME_SERVIDOR}] Evento Geral Recebido: {evento.get('tipo')}")
    # Aqui poderia haver lógica para atualizar caches locais, se existissem.

# Inscreve o servidor em canais relevantes
servico_pubsub.inscrever_e_ouvir(CANAL_EVENTOS_GERAIS, handle_evento_geral)

# --- Endpoints de Status e Teste ---

@app.get("/")
def status_servidor():
    """Retorna o status do servidor e sua URL."""
    estoque_atual = servico_coordenacao.get_estoque_global()
    return {"status": "online", "servidor": NOME_SERVIDOR, "url": URL_LOCAL, "estoque_global": estoque_atual.pacotes_restantes}

@app.get("/servidores")
def listar_servidores():
    """Retorna a lista de URLs de todos os servidores conhecidos."""
    return {"servidores": SERVIDORES_JOGO}

# --- Endpoints de Comunicação Cliente-Servidor (Simulados) ---

@app.post("/jogador/entrar")
def entrar_jogador(nome_jogador: str):
    """Simula a entrada de um jogador no servidor."""
    import uuid
    id_jogador = str(uuid.uuid4())
    jogador = Jogador(id_jogador=id_jogador, nome=nome_jogador, servidor_local=NOME_SERVIDOR)
    
    # Tenta obter o inventário, ou cria um novo
    inventario = servico_coordenacao.get_inventario(id_jogador)
    if not inventario:
        inventario = Inventario(id_jogador=id_jogador, pacotes_disponiveis=1) # Dando 1 pacote inicial
        servico_coordenacao.set_inventario(inventario)
        
    # Publica evento de novo jogador (opcional)
    servico_pubsub.publicar(CANAL_EVENTOS_GERAIS, {"tipo": "novo_jogador", "id_jogador": id_jogador, "servidor": NOME_SERVIDOR})
        
    return {"mensagem": f"Bem-vindo, {nome_jogador}!", "jogador": jogador, "inventario": inventario}

@app.get("/inventario/{id_jogador}")
def ver_inventario(id_jogador: str) -> Inventario:
    """Retorna o inventário de um jogador."""
    inventario = servico_coordenacao.get_inventario(id_jogador)
    if not inventario:
        raise HTTPException(status_code=404, detail="Jogador não encontrado.")
    return inventario

@app.post("/pacote/abrir/{id_jogador}")
def abrir_pacote(id_jogador: str):
    """
    Inicia o processo de abertura de pacote, que utiliza Two-Phase Commit (2PC).
    Este servidor atua como o Coordenador Dinâmico.
    """
    inventario = servico_coordenacao.get_inventario(id_jogador)
    if not inventario:
        raise HTTPException(status_code=404, detail="Jogador não encontrado.")
        
    if inventario.pacotes_disponiveis <= 0:
        raise HTTPException(status_code=400, detail="O jogador não possui pacotes disponíveis para abrir.")

    # Decrementa o pacote do inventário do jogador (localmente)
    inventario.pacotes_disponiveis -= 1
    servico_coordenacao.set_inventario(inventario)
    
    sucesso = servico_2pc.iniciar_transacao_abertura_pacote(id_jogador)
    
    if sucesso:
        inventario_atualizado = servico_coordenacao.get_inventario(id_jogador)
        
        # Publica evento de pacote aberto
        servico_pubsub.publicar(CANAL_NOTIFICACOES_JOGADOR.format(id_jogador=id_jogador), 
                                {"tipo": "pacote_aberto", "status": "sucesso", "cartas_obtidas": inventario_atualizado.cartas[-3:]})
        
        return {
            "status": "sucesso",
            "mensagem": "Pacote aberto com sucesso! Cartas adicionadas ao inventário.",
            "inventario_atualizado": inventario_atualizado
        }
    else:
        # Se falhou, reverte a decrementação local do pacote do jogador
        inventario.pacotes_disponiveis += 1
        servico_coordenacao.set_inventario(inventario)
        
        # Publica evento de falha
        servico_pubsub.publicar(CANAL_NOTIFICACOES_JOGADOR.format(id_jogador=id_jogador), 
                                {"tipo": "pacote_aberto", "status": "falha", "motivo": "Transação 2PC abortada."})
                                
        raise HTTPException(status_code=500, detail="Falha na abertura do pacote. Transação 2PC abortada.")

@app.post("/inventario/troca/{id_jogador_a}/{id_jogador_b}")
def iniciar_troca_cartas(id_jogador_a: str, id_jogador_b: str, id_carta_a: str, id_carta_b: str):
    """
    Inicia o processo de troca de cartas entre dois jogadores, utilizando 2PC.
    """
    # ... (Lógica de verificação inicial omitida para brevidade)
    
    detalhes = DetalhesTroca(
        id_jogador_a=id_jogador_a,
        id_carta_a=id_carta_a,
        id_jogador_b=id_jogador_b,
        id_carta_b=id_carta_b
    )
    
    sucesso = servico_2pc.iniciar_transacao_troca_cartas(detalhes, SERVIDORES_JOGO)
    
    if sucesso:
        # Publica evento de troca concluída
        servico_pubsub.publicar(CANAL_NOTIFICACOES_JOGADOR.format(id_jogador=id_jogador_a), 
                                {"tipo": "troca_cartas", "status": "sucesso", "parceiro": id_jogador_b, "carta_recebida": id_carta_b})
        servico_pubsub.publicar(CANAL_NOTIFICACOES_JOGADOR.format(id_jogador=id_jogador_b), 
                                {"tipo": "troca_cartas", "status": "sucesso", "parceiro": id_jogador_a, "carta_recebida": id_carta_a})
                                
        return {"status": "sucesso", "mensagem": "Troca de cartas concluída com sucesso!"}
    else:
        # Publica evento de falha na troca
        servico_pubsub.publicar(CANAL_NOTIFICACOES_JOGADOR.format(id_jogador=id_jogador_a), 
                                {"tipo": "troca_cartas", "status": "falha", "motivo": "Transação 2PC abortada."})
        servico_pubsub.publicar(CANAL_NOTIFICACOES_JOGADOR.format(id_jogador=id_jogador_b), 
                                {"tipo": "troca_cartas", "status": "falha", "motivo": "Transação 2PC abortada."})
                                
        raise HTTPException(status_code=500, detail="Falha na troca de cartas. Transação 2PC abortada.")


# --- Endpoints de Comunicação Servidor-Servidor (Two-Phase Commit) ---

@app.post("/transacao/abrir_pacote/prepare")
def transacao_prepare_pacote(transacao: Transacao2PC) -> Voto2PC:
    """
    Endpoint de Participante: Recebe a requisição PREPARE do Coordenador (Abertura de Pacote).
    """
    return servico_2pc.participante_prepare_abrir_pacote(transacao)

@app.post("/transacao/abrir_pacote/commit_abort")
def transacao_commit_abort_pacote(resultado: Resultado2PC):
    """
    Endpoint de Participante: Recebe a decisão final (COMMIT ou ABORT) do Coordenador (Abertura de Pacote).
    """
    servico_2pc.participante_commit_abort_abrir_pacote(resultado)
    return {"status": "ok", "mensagem": f"Decisão {resultado.decisao} processada."}

@app.post("/inventario/troca/prepare")
def transacao_prepare_troca(transacao: Transacao2PC) -> Voto2PC:
    """
    Endpoint de Participante: Recebe a requisição PREPARE do Coordenador (Troca de Cartas).
    """
    return servico_2pc.participante_prepare_troca_cartas(transacao)

@app.post("/inventario/troca/commit_abort")
def transacao_commit_abort_troca(resultado: Resultado2PC):
    """
    Endpoint de Participante: Recebe a decisão final (COMMIT ou ABORT) do Coordenador (Troca de Cartas).
    """
    servico_2pc.participante_commit_abort_troca_cartas(resultado)
    return {"status": "ok", "mensagem": f"Decisão {resultado.decisao} processada."}


# --- Endpoints de Pareamento e Partida (A ser implementado) ---

@app.post("/pareamento/solicitar")
def solicitar_pareamento(solicitacao: PareamentoSolicitacao) -> PareamentoResposta:
    """
    Endpoint de Servidor-Servidor: Recebe uma solicitação de pareamento de outro servidor.
    """
    # A implementação completa do pareamento distribuído será feita na próxima fase.
    print(f"Recebida solicitação de pareamento de {solicitacao.servidor_solicitante_url} para {solicitacao.id_jogador_solicitante}")
    
    # Simulação de aceitação
    id_partida = f"PARTIDA-{int(time.time())}"
    
    # Publica evento de pareamento aceito
    servico_pubsub.publicar(CANAL_EVENTOS_GERAIS, 
                            {"tipo": "pareamento_aceito", "id_partida": id_partida, "jogador1": solicitacao.id_jogador_solicitante, "servidor1": solicitacao.servidor_solicitante_url, "servidor2": URL_LOCAL})
    
    return PareamentoResposta(
        aceito=True,
        mensagem="Solicitação recebida e aceita.",
        id_partida=id_partida
    )

@app.post("/partida/jogada")
def registrar_jogada(id_partida: str, id_jogador: str, jogada: str):
    """
    Endpoint de Servidor-Servidor: Registra uma jogada em uma partida coordenada.
    """
    # Lógica da partida será implementada na próxima fase.
    
    # Publica evento de jogada
    servico_pubsub.publicar(f"partida_{id_partida}", 
                            {"tipo": "jogada", "id_jogador": id_jogador, "jogada": jogada})
                            
    return {"status": "ok", "mensagem": f"Jogada {jogada} de {id_jogador} registrada na partida {id_partida}."}
