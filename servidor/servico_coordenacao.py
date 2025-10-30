# -*- coding: utf-8 -*-
import redis
import json
import os
from typing import Optional
from modelos import EstoqueGlobal, Inventario, Transacao2PC

# Configuração do Redis
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))

class ServicoCoordenacao:
    """
    Gerencia o estado global compartilhado (Estoque e Inventários)
    e o log de transações 2PC usando Redis.
    """
    
    def __init__(self):
        # Técnica: Uso de Redis para persistência e sincronização de estado
        # entre múltiplos servidores, evitando o uso de um banco de dados relacional
        # complexo para este tipo de dado.
        self.redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        self.chave_estoque = "estoque_global"
        self.prefixo_inventario = "inventario:"
        self.prefixo_transacao = "transacao_2pc:"
        
        # Inicializa o estoque se não existir
        if not self.redis_client.exists(self.chave_estoque):
            self.set_estoque_global(EstoqueGlobal())

    # --- Gerenciamento de Estoque Global ---
    
    def get_estoque_global(self) -> EstoqueGlobal:
        """Recupera o estado do estoque global do Redis."""
        dados = self.redis_client.get(self.chave_estoque)
        if dados:
            return EstoqueGlobal(**json.loads(dados))
        return EstoqueGlobal() # Retorna o padrão se não encontrar

    def set_estoque_global(self, estoque: EstoqueGlobal):
        """Salva o estado do estoque global no Redis."""
        self.redis_client.set(self.chave_estoque, estoque.json())

    # --- Gerenciamento de Inventário ---
    
    def get_inventario(self, id_jogador: str) -> Optional[Inventario]:
        """Recupera o inventário de um jogador do Redis."""
        dados = self.redis_client.get(f"{self.prefixo_inventario}{id_jogador}")
        if dados:
            return Inventario(**json.loads(dados))
        return None

    def set_inventario(self, inventario: Inventario):
        """Salva o inventário de um jogador no Redis."""
        self.redis_client.set(f"{self.prefixo_inventario}{inventario.id_jogador}", inventario.json())

    # --- Gerenciamento de Transações 2PC ---
    
    def get_transacao(self, id_transacao: str) -> Optional[Transacao2PC]:
        """Recupera o estado de uma transação 2PC do Redis."""
        dados = self.redis_client.get(f"{self.prefixo_transacao}{id_transacao}")
        if dados:
            return Transacao2PC(**json.loads(dados))
        return None

    def set_transacao(self, transacao: Transacao2PC):
        """Salva o estado de uma transação 2PC no Redis."""
        # Técnica: Persistir o estado da transação no Redis para recuperação em caso de falha
        # do Coordenador ou Participante antes da decisão final.
        # O timeout é opcional, mas útil para limpar transações pendentes.
        self.redis_client.set(f"{self.prefixo_transacao}{transacao.id_transacao}", transacao.json())

    def remover_transacao(self, id_transacao: str):
        """Remove uma transação 2PC do Redis após finalização."""
        self.redis_client.delete(f"{self.prefixo_transacao}{id_transacao}")

    # --- Operação Crítica de Estoque (Transação Atômica) ---
    
    def decrementar_estoque_atomico(self, quantidade: int) -> bool:
        """
        Tenta decrementar o estoque global de forma atômica usando transações WATCH/MULTI/EXEC do Redis.
        Técnica: Controle de Concorrência Distribuída (WATCH/MULTI/EXEC).
        """
        chave = self.chave_estoque
        with self.redis_client.pipeline() as pipe:
            while True:
                try:
                    # 1. WATCH a chave do estoque
                    pipe.watch(chave)
                    
                    # 2. Obter o valor atual
                    estoque_atual = self.get_estoque_global()
                    
                    if estoque_atual.pacotes_restantes < quantidade:
                        pipe.unwatch()
                        return False # Estoque insuficiente

                    # 3. MULTI (Início da transação atômica)
                    pipe.multi()
                    
                    # 4. Executar a operação
                    estoque_atual.pacotes_restantes -= quantidade
                    pipe.set(chave, estoque_atual.json())
                    
                    # 5. EXEC (Executa todas as operações se a chave WATCHED não mudou)
                    pipe.execute()
                    return True # Sucesso
                
                except redis.exceptions.WatchError:
                    # A chave mudou, tentar novamente
                    print("Conflito de concorrência no estoque. Tentando novamente...")
                    continue
                except Exception as e:
                    print(f"Erro na transação atômica do Redis: {e}")
                    return False
    
    def incrementar_estoque_atomico(self, quantidade: int):
        """Incrementa o estoque global de forma atômica (usado no ABORT do 2PC)."""
        chave = self.chave_estoque
        with self.redis_client.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(chave)
                    estoque_atual = self.get_estoque_global()
                    pipe.multi()
                    estoque_atual.pacotes_restantes += quantidade
                    pipe.set(chave, estoque_atual.json())
                    pipe.execute()
                    return True
                except redis.exceptions.WatchError:
                    print("Conflito de concorrência no estoque (incremento). Tentando novamente...")
                    continue
                except Exception as e:
                    print(f"Erro na transação atômica do Redis (incremento): {e}")
                    return False
