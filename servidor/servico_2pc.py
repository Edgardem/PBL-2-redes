# -*- coding: utf-8 -*-
import requests
import json
import uuid
import os
from typing import List, Dict, Optional
from modelos import Transacao2PC, Voto2PC, Resultado2PC, Inventario, Carta, DetalhesTroca
from servico_coordenacao import ServicoCoordenacao

# Simulação da lista de servidores (agora lida da variável de ambiente)
# Técnica: Uso de variável de ambiente para configurar a topologia da rede
# em um ambiente distribuído (Docker Compose).
SERVIDORES_JOGO_ENV = os.environ.get("SERVIDORES_JOGO", "")
SERVIDORES_JOGO: List[str] = [url.strip() for url in SERVIDORES_JOGO_ENV.split(',') if url.strip()]

# --- Lógica de Negócio (Simulação de Abertura de Pacote) ---

def gerar_carta(id_jogador: str) -> Carta:
    """Função simulada para gerar uma carta com skin."""
    import random
    tipos = ["pedra", "papel", "tesoura"]
    skins = {
        "pedra": ["Rocha Vulcânica", "Mármore Polido", "Seixo de Rio"],
        "papel": ["Papiro Antigo", "Jornal Velho", "Nota de Dólar"],
        "tesoura": ["Lâmina Afiada", "Tesoura de Jardim", "Navalha de Barbeiro"]
    }
    raridades = ["Comum", "Comum", "Comum", "Rara", "Rara", "Épica", "Lendária"]

    tipo_escolhido = random.choice(tipos)
    skin_escolhida = random.choice(skins[tipo_escolhido])
    raridade_escolhida = random.choice(raridades)

    return Carta(
        id_carta=f"CARTA-{random.randint(1000, 9999)}",
        nome=f"{tipo_escolhido.capitalize()} ({skin_escolhida})",
        tipo=tipo_escolhido,
        skin=skin_escolhida,
        raridade=raridade_escolhida
    )

def simular_abertura_pacote(id_jogador: str) -> List[Carta]:
    """Simula a abertura de um pacote, retornando 3 cartas."""
    cartas_obtidas = [gerar_carta(id_jogador) for _ in range(3)]
    return cartas_obtidas

# --- Implementação do Two-Phase Commit (2PC) ---

class Servico2PC:
    def __init__(self, url_local: str, servico_coordenacao: ServicoCoordenacao):
        self.url_local = url_local
        self.servico_coordenacao = servico_coordenacao
        
        # A lista de servidores deve ser lida após a inicialização do Servico2PC
        # para garantir que a variável de ambiente SERVIDORES_JOGO foi populada.
        SERVIDORES_JOGO_ENV = os.environ.get("SERVIDORES_JOGO", "")
        self.servidores_jogo: List[str] = [url.strip() for url in SERVIDORES_JOGO_ENV.split(',') if url.strip()]
        
        # Filtra a lista de servidores para obter os Participantes remotos
        self.outros_servidores = [url for url in self.servidores_jogo if url != url_local]
        
        # Técnica: Dicionário local para transações em andamento (cache)
        self.transacoes_em_andamento: Dict[str, Transacao2PC] = {}

    # --- Funções Auxiliares de Comunicação ---
    
    def _enviar_prepare(self, servidor_url: str, transacao: Transacao2PC, endpoint: str) -> Optional[Voto2PC]:
        """Envia a requisição PREPARE para um Participante."""
        try:
            print(f"[{self.url_local}] Coordenador: Enviando PREPARE ({endpoint}) para {servidor_url}...")
            response = requests.post(
                f"{servidor_url}{endpoint}",
                json=transacao.dict(),
                timeout=5
            )
            response.raise_for_status()
            return Voto2PC(**response.json())
        except requests.exceptions.RequestException as e:
            # Técnica: Tolerância a Falhas. A falha de comunicação implica em ABORT.
            print(f"[{self.url_local}] Coordenador: Falha de comunicação com {servidor_url} ({e}). ABORT.")
            return None

    def _enviar_decisao(self, servidor_url: str, resultado: Resultado2PC, endpoint: str):
        """Envia a decisão final (COMMIT ou ABORT) para um Participante."""
        try:
            requests.post(
                f"{servidor_url}{endpoint}",
                json=resultado.dict(),
                timeout=5
            )
        except requests.exceptions.RequestException as e:
            # Técnica: Recuperação. O Participante que falhou em receber a decisão
            # deve ter um mecanismo de recuperação (ex: log de transação e consulta ao Coordenador)
            print(f"[{self.url_local}] Coordenador: Falha ao enviar {resultado.decisao} para {servidor_url}. Necessita de recuperação.")

    def _finalizar_transacao_generica(self, id_transacao: str, decisao: str, endpoint_commit_abort: str):
        """Lógica genérica para enviar a decisão final (COMMIT ou ABORT) para todos os Participantes."""
        transacao = self.transacoes_em_andamento.get(id_transacao)
        if not transacao:
            transacao = self.servico_coordenacao.get_transacao(id_transacao)
            if not transacao:
                print(f"[{self.url_local}] Coordenador: Transação {id_transacao} não encontrada para finalização.")
                return

        # Executar a decisão localmente
        resultado_local = Resultado2PC(id_transacao=id_transacao, servidor_url=self.url_local, decisao=decisao)
        
        if transacao.tipo_operacao == "abrir_pacote":
            self._participante_commit_abort_abrir_pacote_logica(resultado_local)
        elif transacao.tipo_operacao == "troca_cartas":
            self._participante_commit_abort_troca_cartas_logica(resultado_local)
        
        # Enviar a decisão para os Participantes remotos
        for servidor_url in self.outros_servidores:
            self._enviar_decisao(servidor_url, resultado_local, endpoint_commit_abort)

        # Remover transação da lista de pendentes
        self.transacoes_em_andamento.pop(id_transacao, None)
        self.servico_coordenacao.remover_transacao(id_transacao)

    # --- 2PC para Abertura de Pacotes ---
    
    def iniciar_transacao_abertura_pacote(self, id_jogador: str) -> bool:
        """
        Inicia o 2PC para abertura de um pacote. O servidor local é o Coordenador Dinâmico.
        """
        id_transacao = str(uuid.uuid4())
        
        transacao = Transacao2PC(
            id_transacao=id_transacao,
            coordenador_url=self.url_local,
            tipo_operacao="abrir_pacote",
            status="PREPARAR",
            dados={"id_jogador": id_jogador, "quantidade_pacotes": 1}
        )
        self.transacoes_em_andamento[id_transacao] = transacao
        self.servico_coordenacao.set_transacao(transacao)
        print(f"[{self.url_local}] Coordenador: Transação {id_transacao} de abertura de pacote iniciada.")

        # Fase de Voto (Prepare)
        votos_commit = 0
        
        # Voto local
        voto_local = self._participante_prepare_abrir_pacote_logica(transacao)
        if voto_local.voto == "VOTE_COMMIT":
            votos_commit += 1
        else:
            self._finalizar_transacao_generica(id_transacao, "GLOBAL_ABORT", "/transacao/abrir_pacote/commit_abort")
            return False
            
        # Votos remotos
        for servidor_url in self.outros_servidores:
            voto_remoto = self._enviar_prepare(servidor_url, transacao, "/transacao/abrir_pacote/prepare")
            
            if voto_remoto and voto_remoto.voto == "VOTE_COMMIT":
                votos_commit += 1
            else:
                # Técnica: Se um Participante falha (timeout ou ABORT), o Coordenador aborta.
                self._finalizar_transacao_generica(id_transacao, "GLOBAL_ABORT", "/transacao/abrir_pacote/commit_abort")
                return False

        # Fase de Decisão (Commit)
        if votos_commit == len(self.servidores_jogo):
            print(f"[{self.url_local}] Coordenador: Todos votaram COMMIT. Enviando GLOBAL_COMMIT.")
            self._finalizar_transacao_generica(id_transacao, "GLOBAL_COMMIT", "/transacao/abrir_pacote/commit_abort")
            return True
        else:
            self._finalizar_transacao_generica(id_transacao, "GLOBAL_ABORT", "/transacao/abrir_pacote/commit_abort")
            return False

    def _participante_prepare_abrir_pacote_logica(self, transacao: Transacao2PC) -> Voto2PC:
        """
        Recebe a requisição PREPARE e vota COMMIT ou ABORT para abertura de pacote.
        Técnica: Two-Phase Commit (2PC) - Fase de Voto.
        """
        id_transacao = transacao.id_transacao
        self.transacoes_em_andamento[id_transacao] = transacao
        self.servico_coordenacao.set_transacao(transacao)
        
        # Técnica: Uso de transação atômica (WATCH/MULTI/EXEC) no Redis para o estoque global.
        if not self.servico_coordenacao.decrementar_estoque_atomico(transacao.dados["quantidade_pacotes"]):
            return Voto2PC(
                id_transacao=id_transacao,
                servidor_url=self.url_local,
                voto="VOTE_ABORT",
                mensagem="Estoque global esgotado ou conflito de concorrência."
            )
        
        print(f"[{self.url_local}] Participante: Votou COMMIT para transação {id_transacao} (abertura de pacote).")
        return Voto2PC(id_transacao=id_transacao, servidor_url=self.url_local, voto="VOTE_COMMIT")

    def participante_prepare_abrir_pacote(self, transacao: Transacao2PC) -> Voto2PC:
        """Endpoint wrapper para a lógica de PREPARE de abertura de pacote."""
        return self._participante_prepare_abrir_pacote_logica(transacao)

    def _participante_commit_abort_abrir_pacote_logica(self, resultado: Resultado2PC):
        """
        Recebe a decisão final (COMMIT ou ABORT) do Coordenador para abertura de pacote.
        Técnica: Two-Phase Commit (2PC) - Fase de Decisão.
        """
        id_transacao = resultado.id_transacao
        transacao = self.transacoes_em_andamento.pop(id_transacao, None)
        
        if not transacao:
            transacao = self.servico_coordenacao.get_transacao(id_transacao)
            if not transacao:
                print(f"[{self.url_local}] Participante: Transação {id_transacao} já finalizada ou não encontrada.")
                return

        id_jogador = transacao.dados["id_jogador"]
        
        if resultado.decisao == "GLOBAL_COMMIT":
            # Executar a transação: Adicionar cartas ao inventário do jogador
            inventario = self.servico_coordenacao.get_inventario(id_jogador)
            if not inventario:
                inventario = Inventario(id_jogador=id_jogador)

            cartas_obtidas = simular_abertura_pacote(id_jogador)
            inventario.cartas.extend(cartas_obtidas)
            self.servico_coordenacao.set_inventario(inventario)
            
            print(f"[{self.url_local}] Participante: COMMIT da transação {id_transacao} (abertura de pacote) executado. Cartas adicionadas.")
            
        elif resultado.decisao == "GLOBAL_ABORT":
            # Desfazer a transação (rollback): Devolver o pacote ao estoque
            self.servico_coordenacao.incrementar_estoque_atomico(transacao.dados["quantidade_pacotes"])
            print(f"[{self.url_local}] Participante: ABORT da transação {id_transacao} (abertura de pacote) executado. Pacote devolvido.")
            
        self.servico_coordenacao.remover_transacao(id_transacao)

    def participante_commit_abort_abrir_pacote(self, resultado: Resultado2PC):
        """Endpoint wrapper para a lógica de COMMIT/ABORT de abertura de pacote."""
        return self._participante_commit_abort_abrir_pacote_logica(resultado)

    # --- 2PC para Troca de Cartas ---
    
    def iniciar_transacao_troca_cartas(self, detalhes_troca: DetalhesTroca, participantes_url: List[str]) -> bool:
        """
        Inicia o 2PC para troca de cartas. O servidor local é o Coordenador Dinâmico.
        """
        id_transacao = str(uuid.uuid4())
        
        transacao = Transacao2PC(
            id_transacao=id_transacao,
            coordenador_url=self.url_local,
            tipo_operacao="troca_cartas",
            status="PREPARAR",
            dados=detalhes_troca.dict()
        )
        self.transacoes_em_andamento[id_transacao] = transacao
        self.servico_coordenacao.set_transacao(transacao)
        print(f"[{self.url_local}] Coordenador: Transação {id_transacao} de troca de cartas iniciada.")

        # Fase de Voto (Prepare)
        votos_commit = 0
        
        # Votos de todos os servidores
        for servidor_url in self.servidores_jogo:
            if servidor_url == self.url_local:
                voto = self._participante_prepare_troca_cartas_logica(transacao)
            else:
                voto = self._enviar_prepare(servidor_url, transacao, "/inventario/troca/prepare")

            if voto and voto.voto == "VOTE_COMMIT":
                votos_commit += 1
            else:
                self._finalizar_transacao_generica(id_transacao, "GLOBAL_ABORT", "/inventario/troca/commit_abort")
                return False

        # Fase de Decisão (Commit)
        if votos_commit == len(self.servidores_jogo):
            print(f"[{self.url_local}] Coordenador: Todos votaram COMMIT. Enviando GLOBAL_COMMIT.")
            self._finalizar_transacao_generica(id_transacao, "GLOBAL_COMMIT", "/inventario/troca/commit_abort")
            return True
        else:
            self._finalizar_transacao_generica(id_transacao, "GLOBAL_ABORT", "/inventario/troca/commit_abort")
            return False

    def _participante_prepare_troca_cartas_logica(self, transacao: Transacao2PC) -> Voto2PC:
        """
        Recebe a requisição PREPARE e vota COMMIT ou ABORT para troca de cartas.
        Técnica: Two-Phase Commit (2PC) - Fase de Voto.
        """
        id_transacao = transacao.id_transacao
        self.transacoes_em_andamento[id_transacao] = transacao
        self.servico_coordenacao.set_transacao(transacao)
        
        detalhes: DetalhesTroca = DetalhesTroca(**transacao.dados)
        
        # 1. Verificar posse das cartas (Simulação de Lock)
        inventario_a = self.servico_coordenacao.get_inventario(detalhes.id_jogador_a)
        inventario_b = self.servico_coordenacao.get_inventario(detalhes.id_jogador_b)
        
        # Apenas os servidores que possuem os jogadores A ou B precisam fazer a verificação crítica
        
        # Verificação de posse e bloqueio (Simulado: Apenas verifica se a carta existe)
        if inventario_a and not any(c.id_carta == detalhes.id_carta_a for c in inventario_a.cartas):
            return Voto2PC(id_transacao=id_transacao, servidor_url=self.url_local, voto="VOTE_ABORT", mensagem=f"Jogador A não possui a carta {detalhes.id_carta_a}.")
        
        if inventario_b and not any(c.id_carta == detalhes.id_carta_b for c in inventario_b.cartas):
            return Voto2PC(id_transacao=id_transacao, servidor_url=self.url_local, voto="VOTE_ABORT", mensagem=f"Jogador B não possui a carta {detalhes.id_carta_b}.")
        
        print(f"[{self.url_local}] Participante: Votou COMMIT para transação {id_transacao} (troca de cartas).")
        return Voto2PC(id_transacao=id_transacao, servidor_url=self.url_local, voto="VOTE_COMMIT")

    def participante_prepare_troca_cartas(self, transacao: Transacao2PC) -> Voto2PC:
        """Endpoint wrapper para a lógica de PREPARE de troca de cartas."""
        return self._participante_prepare_troca_cartas_logica(transacao)

    def _participante_commit_abort_troca_cartas_logica(self, resultado: Resultado2PC):
        """
        Recebe a decisão final (COMMIT ou ABORT) do Coordenador para troca de cartas.
        Técnica: Two-Phase Commit (2PC) - Fase de Decisão.
        """
        id_transacao = resultado.id_transacao
        transacao = self.transacoes_em_andamento.pop(id_transacao, None)
        
        if not transacao:
            transacao = self.servico_coordenacao.get_transacao(id_transacao)
            if not transacao:
                print(f"[{self.url_local}] Participante: Transação {id_transacao} já finalizada ou não encontrada.")
                return
        
        detalhes: DetalhesTroca = DetalhesTroca(**transacao.dados)
        
        if resultado.decisao == "GLOBAL_COMMIT":
            # Executar a transação: Trocar as cartas
            inventario_a = self.servico_coordenacao.get_inventario(detalhes.id_jogador_a)
            inventario_b = self.servico_coordenacao.get_inventario(detalhes.id_jogador_b)
            
            # Técnica: Consistência. A troca só ocorre se ambos os inventários existirem.
            if inventario_a and inventario_b:
                # Encontra as cartas
                carta_a = next((c for c in inventario_a.cartas if c.id_carta == detalhes.id_carta_a), None)
                carta_b = next((c for c in inventario_b.cartas if c.id_carta == detalhes.id_carta_b), None)

                if carta_a and carta_b:
                    # Remove e adiciona as cartas
                    inventario_a.cartas.remove(carta_a)
                    inventario_b.cartas.remove(carta_b)
                    
                    inventario_a.cartas.append(carta_b)
                    inventario_b.cartas.append(carta_a)
                    
                    self.servico_coordenacao.set_inventario(inventario_a)
                    self.servico_coordenacao.set_inventario(inventario_b)
                    
                    print(f"[{self.url_local}] Participante: COMMIT da transação {id_transacao} (troca de cartas) executado. Troca concluída.")
                else:
                    print(f"[{self.url_local}] Participante: ERRO CRÍTICO: Carta não encontrada no COMMIT. Inconsistência detectada.")
            
        elif resultado.decisao == "GLOBAL_ABORT":
            # Desfazer a transação (rollback): Não é necessário, pois a pré-execução foi apenas uma verificação.
            print(f"[{self.url_local}] Participante: ABORT da transação {id_transacao} (troca de cartas) executado. Nada foi alterado.")
            
        self.servico_coordenacao.remover_transacao(id_transacao)

    def participante_commit_abort_troca_cartas(self, resultado: Resultado2PC):
        """Endpoint wrapper para a lógica de COMMIT/ABORT de troca de cartas."""
        return self._participante_commit_abort_troca_cartas_logica(resultado)
