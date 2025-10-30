# -*- coding: utf-8 -*-
from pydantic import BaseModel
from typing import List, Dict, Optional

# --- Modelos de Dados do Jogo ---

class Carta(BaseModel):
    """Representa uma carta do jogo Pedra, Papel, Tesoura com uma skin."""
    id_carta: str
    nome: str
    tipo: str  # 'pedra', 'papel', 'tesoura'
    skin: str
    raridade: str # Ex: Comum, Rara, Épica, Lendária

class Jogador(BaseModel):
    """Representa um jogador conectado ao sistema."""
    id_jogador: str
    nome: str
    servidor_local: str # Identificador do servidor ao qual o jogador está conectado
    ping_udp: Optional[float] = None # Latência medida via UDP

class Inventario(BaseModel):
    """Armazena as cartas e pacotes de um jogador."""
    id_jogador: str
    cartas: List[Carta] = []
    pacotes_disponiveis: int = 0

class EstoqueGlobal(BaseModel):
    """Representa o estoque de pacotes compartilhado entre todos os servidores."""
    pacotes_restantes: int = 50

# --- Modelos para Comunicação Servidor-Servidor (API REST e 2PC) ---

class Transacao2PC(BaseModel):
    """Metadados de uma transação Two-Phase Commit."""
    id_transacao: str
    coordenador_url: str # URL do servidor que iniciou a transação
    tipo_operacao: str # 'abrir_pacote' ou 'troca_cartas'
    status: str # 'PREPARAR', 'VOTAR', 'GLOBAL_COMMIT', 'GLOBAL_ABORT'
    dados: Dict # Dados específicos da transação (ex: id_jogador, quantidade)

class Voto2PC(BaseModel):
    """Resposta de um Participante na Fase de Voto do 2PC."""
    id_transacao: str
    servidor_url: str
    voto: str # 'VOTE_COMMIT' ou 'VOTE_ABORT'
    mensagem: Optional[str] = None

class Resultado2PC(BaseModel):
    """Mensagem de Commit/Abort enviada pelo Coordenador na Fase de Decisão."""
    id_transacao: str
    servidor_url: str
    decisao: str # 'GLOBAL_COMMIT' ou 'GLOBAL_ABORT'

class DetalhesTroca(BaseModel):
    """Detalhes da troca de cartas entre dois jogadores."""
    id_jogador_a: str
    id_carta_a: str
    id_jogador_b: str
    id_carta_b: str

class PareamentoSolicitacao(BaseModel):
    """Solicitação de pareamento de um servidor para outro."""
    id_jogador_solicitante: str
    servidor_solicitante_url: str
    tipo_jogo: str = "Pedra-Papel-Tesoura 1v1"

class PareamentoResposta(BaseModel):
    """Resposta a uma solicitação de pareamento."""
    aceito: bool
    mensagem: str
    id_partida: Optional[str] = None

class Partida(BaseModel):
    """Representa o estado de uma partida 1v1."""
    id_partida: str
    jogador1_id: str
    jogador2_id: str
    servidor1_url: str
    servidor2_url: str
    status: str # 'INICIADA', 'AGUARDANDO_JOGADA', 'FINALIZADA'
    historico_jogadas: List[Dict] = []
    vencedor_id: Optional[str] = None
