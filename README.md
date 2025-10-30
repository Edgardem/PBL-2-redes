# Pedra-Papel-Tesoura Distribuído: Sistema de Jogo em Arquitetura Descentralizada

## Visão Geral do Projeto

Este projeto implementa um jogo de cartas **Pedra-Papel-Tesoura** com funcionalidades de inventário, abertura de pacotes e partidas 1v1, utilizando uma **arquitetura distribuída e descentralizada** em Python (FastAPI) e orquestrada com Docker. O sistema foi projetado para operar em múltiplos servidores regionais (Norte, Nordeste, Centro-Oeste, Sudeste, Sul) sem pontos únicos de falha, garantindo a **consistência** e a **atomicidade** de transações críticas através do protocolo **Two-Phase Commit (2PC)**.

O código-fonte utiliza variáveis em português, conforme solicitado.

## 1. Instalação e Execução

O sistema é executado inteiramente em contêineres Docker, simulando um ambiente distribuído em máquinas distintas.

### Pré-requisitos

*   Docker e Docker Compose instalados.

### Passos de Execução

1.  **Navegue** até o diretório raiz do projeto (`pedra_papel_tesoura_distribuido`).
2.  **Inicie** a orquestração com Docker Compose:

    ```bash
    docker-compose up --build -d
    ```

    Isso inicializará 8 contêineres: 1 Redis (coordenação), 5 Servidores de Jogo (um para cada região) e 2 Clientes de Teste (Norte e Sul).

3.  **Acesse os Clientes Interativos (CMD):**

    Para interagir com o sistema, use os clientes de teste pré-configurados:

    ```bash
    # Cliente conectado ao Servidor Norte (porta 8001)
    docker attach cliente_teste_norte

    # Cliente conectado ao Servidor Sul (porta 8005)
    docker attach cliente_teste_sul
    ```

4.  **Acesse as APIs (Insomnia/Postman):**

    Os servidores de jogo estão expostos nas seguintes portas:
    *   Servidor Norte: `http://localhost:8001`
    *   Servidor Nordeste: `http://localhost:8002`
    *   Servidor Centro-Oeste: `http://localhost:8003`
    *   Servidor Sudeste: `http://localhost:8004`
    *   Servidor Sul: `http://localhost:8005`

    A documentação OpenAPI (Swagger UI) de cada servidor está disponível em `http://localhost:[PORTA]/docs`.

---

## Barema de Avaliação

### 1. Arquitetura Distribuída e Escalabilidade

**Requisito:** Explique como a solução migrou de centralizada para distribuída utilizando múltiplos servidores de jogos e descreva aspectos da arquitetura relacionados a comunicação e escalabilidade de seus componentes.

**Solução Adotada:**
A solução migra de um modelo centralizado (onde um único servidor gerencia todo o estado) para uma **arquitetura distribuída e descentralizada** composta por 5 servidores de jogo regionais (Norte, Nordeste, Centro-Oeste, Sudeste, Sul).

*   **Descentralização:** Cada servidor é capaz de atuar como **Coordenador Dinâmico** para transações distribuídas (2PC) e gerenciar a lógica de jogo para os clientes conectados.
*   **Componentes:**
    *   **Servidores de Jogo (FastAPI):** Lógica de negócio, API REST para comunicação Servidor-Servidor e Cliente-Servidor.
    *   **Redis (Serviço de Coordenação):** Atua como um repositório de estado consistente para dados globais (Estoque de Pacotes) e inventários, além de fornecer o mecanismo de Pub/Sub.
*   **Escalabilidade:** A arquitetura é horizontalmente escalável. Novos servidores regionais podem ser adicionados ao `docker-compose.yml` e à lista de `SERVIDORES_JOGO`, aumentando a capacidade de processamento e reduzindo a latência para clientes em novas regiões.

### 2. Comunicação Servidor-Servidor

**Requisito:** O sistema deve implementar a comunicação entre servidores através de um protocolo baseado em API REST. Liste e descreva os principais *endpoints* criados para a colaboração entre servidores, especialmente aqueles relacionados à gestão de recursos compartilhados (Ex: estoque de pacotes) e pareamento.

**Solução Adotada:**
A comunicação Servidor-Servidor é baseada em **API RESTful** síncrona, essencial para o protocolo 2PC.

| Método | Endpoint | Descrição |
| :--- | :--- | :--- |
| `POST` | `/transacao/abrir_pacote/prepare` | **2PC - Fase de Voto:** Recebido por Participantes. Verifica estoque global e vota `COMMIT` ou `ABORT`. |
| `POST` | `/transacao/abrir_pacote/commit_abort` | **2PC - Fase de Decisão:** Recebido por Participantes. Executa `COMMIT` (adiciona cartas) ou `ABORT` (devolve pacote ao estoque). |
| `POST` | `/inventario/troca/prepare` | **2PC - Troca:** Recebido por Participantes. Verifica posse das cartas e vota. |
| `POST` | `/inventario/troca/commit_abort` | **2PC - Troca:** Executa `COMMIT` (troca as cartas nos inventários) ou `ABORT`. |
| `POST` | `/pareamento/solicitar` | Recebe uma solicitação de pareamento de um jogador conectado a outro servidor. |

### 3. Comunicação Cliente-Servidor

**Requisito:** O sistema deve utilizar um protocolo baseado no modelo *publisher-subscriber* para a comunicação entre servidores e clientes. Identifique a biblioteca de terceiros (se usada) e justifique sua escolha.

**Solução Adotada:**
O sistema utiliza o **Redis** e seu recurso nativo de **Pub/Sub** para comunicação assíncrona de eventos.

*   **Biblioteca:** `redis-py`.
*   **Justificativa:** O Redis já é utilizado para coordenação e estado global (Estoque/Inventários), evitando a necessidade de introduzir um novo serviço de mensageria (como Kafka ou RabbitMQ). O Pub/Sub do Redis é simples, rápido e ideal para notificações em tempo real.
*   **Canais Principais:**
    *   `eventos_gerais`: Para eventos que afetam todos os servidores (ex: pareamento aceito).
    *   `notificacoes_jogador_[ID]`: Canal privado para notificações específicas do cliente (ex: `pacote_aberto`, `troca_concluida`).

### 4. Gerenciamento Distribuído de Estoque

**Requisito:** Demonstre que a solução não centralizada empregada para garantir que a distribuição de cartas (pacotes únicos, "estoque global") seja justa, impedindo duplicações ou perdas de cartas quando múltiplos jogadores conectados a diferentes servidores tentam abrir pacotes simultaneamente. Discuta o controle de concorrência distribuída implementado.

**Solução Adotada:**
A gestão do estoque de 50 pacotes é feita de forma **consistente** e **atômica** em um ambiente distribuído, combinando o Redis e o Two-Phase Commit.

1.  **Controle de Concorrência (Redis):** O `ServicoCoordenacao` utiliza a transação **WATCH/MULTI/EXEC** do Redis para a operação crítica de decremento do estoque.
    *   **Técnica:** `WATCH` monitora a chave do estoque. `MULTI` inicia a transação. A decrementação só é executada via `EXEC` se a chave não tiver sido alterada por outro cliente, garantindo que a verificação (`estoque > 0`) e a atualização (`estoque = estoque - 1`) sejam atômicas, eliminando condições de corrida.

2.  **Atomicidade (2PC):** O Two-Phase Commit garante que a operação de abertura de pacote (que envolve a decrementação do estoque e a adição das cartas ao inventário) seja **Tudo ou Nada**.
    *   **Fase de Voto:** Todos os 5 servidores (Participantes) tentam executar a decrementação atômica do estoque no Redis. Se qualquer um falhar (por concorrência ou estoque esgotado), o voto é `ABORT`.
    *   **Fase de Decisão:** Se houver um único `ABORT` ou falha de comunicação (timeout), o Coordenador envia `GLOBAL_ABORT`, revertendo qualquer alteração.

### 5. Consistência e Justiça do Estado do Jogo

**Requisito:** Explique como o sistema garante a consistência do estado do jogo (ex: saldo de cartas, progresso da partida) entre os múltiplos servidores, especialmente ao implementar a troca de cartas entre jogadores.

**Solução Adotada:**
A consistência é garantida pelo uso do **Redis como repositório de estado único (SSOT - Single Source of Truth)** para dados críticos (Inventários e Estoque).

*   **Troca de Cartas (2PC):** A troca de cartas entre dois jogadores, potencialmente conectados a servidores diferentes, utiliza o 2PC.
    *   O Coordenador (servidor que inicia a troca) envia `PREPARE` para todos os 5 servidores.
    *   Os Participantes verificam se as cartas existem nos inventários (que estão no Redis).
    *   Somente após o `GLOBAL_COMMIT`, as cartas são **removidas** do inventário de um jogador e **adicionadas** ao do outro no Redis, garantindo que a troca seja atômica e que o estado final seja consistente em todos os servidores.

### 6. Pareamento em Ambiente Distribuído

**Requisito:** Demonstre que o sistema permite que jogadores conectados a servidores diferentes possam ser pareados para duelos 1v1, mantendo as garantias de pareamento único (evitando que um jogador seja pareado com múltiplos oponentes).

**Solução Adotada:**
O pareamento é iniciado por um cliente e coordenado via API REST e Pub/Sub.

1.  **Iniciação:** O Cliente envia uma requisição de pareamento (`POST /pareamento/solicitar`) para seu servidor local.
2.  **Coordenação Distribuída (Simulada):** O servidor local (Coordenador) poderia usar uma fila de pareamento no Redis. Para a demonstração, ele envia uma solicitação de pareamento para **outro servidor** (simulando a busca por um oponente).
3.  **Aceitação e Notificação (Pub/Sub):** O servidor que aceita o pareamento gera um ID de partida e publica um evento (`pareamento_aceito`) no canal `eventos_gerais`.
4.  **Garantia de Unicidade:** A lógica completa de pareamento (que não foi totalmente implementada para focar no 2PC) exigiria um mecanismo de *lock* no Redis (ex: Redlock) para garantir que, ao encontrar um oponente, o status de ambos os jogadores seja bloqueado antes da notificação, prevenindo múltiplos pareamentos.

### 7. Tolerância a Falhas e Resiliência

**Requisito:** Explique as estratégias implementadas para que o sistema seja tolerante a falhas de um ou mais servidores de jogo durante uma partida ou operação, minimizando o impacto nos jogadores e garantindo a continuidade do serviço.

**Estratégias Implementadas:**

| Estratégia | Descrição |
| :--- | :--- |
| **2PC (Two-Phase Commit)** | Em transações críticas (abertura de pacote, troca de cartas), a falha de comunicação (timeout) com **qualquer** Participante resulta em `GLOBAL_ABORT`. Isso garante a **consistência** (nenhuma transação parcial é concluída) em detrimento da disponibilidade. |
| **Persistência de Transação (Redis)** | O estado da transação 2PC é persistido no Redis. Se o Coordenador falhar após a Fase de Voto, mas antes da Fase de Decisão, um Participante pode consultar o log no Redis para determinar a decisão final (mecanismo de recuperação). |
| **Descentralização** | Qualquer um dos 5 servidores pode se tornar o Coordenador Dinâmico. A falha de um servidor não impede que outros servidores iniciem novas transações. |
| **Comunicação Assíncrona (Pub/Sub)** | A falha de um servidor não interrompe a entrega de eventos para outros clientes/servidores. O Redis armazena os eventos até que os clientes se reconectem. |

### 8. Testes de Software e Validação

**Requisito:** Deve ser desenvolvido e apresentado um teste de software para verificar a validade da solução em situações de concorrência distribuída e cenários de falha. O README deve incluir os scripts de testes.

**Solução Adotada:**
O script `teste_concorrencia.py` (disponível no diretório raiz) simula os cenários críticos.

#### Scripts de Teste

1.  **`teste_concorrencia_abertura_pacotes`:** Simula 60 clientes em 5 servidores tentando abrir pacotes. **Valida:** O estoque global (50) é consumido atomicamente, e o número de sucessos é igual à diferença entre o estoque inicial e o final.
2.  **`teste_falha_2pc_abort`:** Simula o esgotamento do estoque e tenta uma última abertura. **Valida:** A transação é abortada, e o estoque não é alterado (rollback).
3.  **`teste_troca_cartas_2pc`:** Simula a troca de cartas entre dois jogadores em servidores diferentes. **Valida:** A posse das cartas é transferida corretamente (consistência).

#### Como Rodar os Testes

Com os contêineres Docker em execução (`docker-compose up -d`), execute o script de teste no host:

```bash
python3 teste_concorrencia.py
```

### 9. Emprego do Docker e Emulação Realista

**Requisito:** Demonstre que os componentes (clientes e múltiplos servidores) foram desenvolvidos e testados em contêineres Docker. O sistema deve ser executado em contêineres separados e em computadores distintos no laboratório para uma emulação realista do cenário proposto.

**Solução Adotada:**
A orquestração via `docker-compose.yml` emula o ambiente distribuído:

*   **Contêineres Separados:** 8 contêineres distintos (1 Redis, 5 Servidores de Jogo, 2 Clientes de Teste).
*   **Emulação de Máquinas Distintas:** Todos os serviços se comunicam através de uma rede Docker (`rede_jogo`), utilizando nomes de serviço (ex: `servidor_norte`, `redis`), simulando a comunicação entre máquinas diferentes em um datacenter.
*   **Múltiplos Servidores (Regiões):** Cada servidor de jogo é uma instância separada, configurada com sua própria variável `NOME_SERVIDOR`, simulando a distribuição regional.

### 10. Documentação e Qualidade do Produto

**Requisito:** O grupo deve entregar o relatório no formato SBC (máximo 8 páginas), contendo os conceitos e justificativas para a solução adotada. O código-fonte deve estar devidamente comentado e disponível no GitHub, junto com o README explicando a execução e os testes.

**Solução Adotada:**
*   **Comentários no Código:** O código-fonte (`servidor/*.py` e `cliente/*.py`) está comentado, destacando as **técnicas de sistemas distribuídos** utilizadas (ex: Two-Phase Commit, Redis WATCH/MULTI/EXEC, Pub/Sub, Listener UDP).
*   **Qualidade:** O código segue o princípio de **Clean Code**, utilizando o framework FastAPI e Pydantic para tipagem e validação de dados.
*   **README:** Este documento serve como o relatório técnico e guia de execução, cobrindo todos os requisitos do barema.

---

## Estrutura do Projeto

```
pedra_papel_tesoura_distribuido/
├── servidor/
│   ├── main.py               # Aplicação FastAPI (Endpoints, UDP Listener)
│   ├── modelos.py            # Classes de dados (Pydantic) em português
│   ├── servico_2pc.py        # Lógica do Two-Phase Commit (Abertura/Troca)
│   ├── servico_coordenacao.py# Gerencia estado global (Estoque/Inventário) via Redis
│   └── servico_pubsub.py     # Lógica de comunicação assíncrona (Redis Pub/Sub)
├── cliente/
│   └── cliente_cmd.py        # Interface interativa CMD (Menu, Latência UDP)
├── teste_concorrencia.py     # Script de validação de 2PC e concorrência
├── Dockerfile.servidor       # Imagem Docker para Servidores de Jogo
├── Dockerfile.cliente        # Imagem Docker para Clientes CMD
├── docker-compose.yml        # Orquestração dos 5 Servidores, Redis e 2 Clientes
└── README.md                 # Documentação (Este arquivo)
```
