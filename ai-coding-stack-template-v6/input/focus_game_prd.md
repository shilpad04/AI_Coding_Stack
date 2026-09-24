# Product Requirements Document: Focus (Domination) Board Game

## 1. Project Overview

### 1.1 Project Name
**Focus** (also known as *Domination* by Sid Sackson)

### 1.2 Product Summary
Focus is a web application implementation of Sid Sackson's 1963 abstract strategy board game *Focus* (winner of the 1981 Spiel des Jahres). The game features a modified 8x8 checkerboard (52 playable squares) where a single Human player competes exclusively against an AI opponent. The system consists of a Vite (React/TypeScript) frontend for board rendering/interactions and a FastAPI (Python) backend for game rules validation and AI decision-making. No database is used; all match state is held in-memory and communicated via REST API endpoints.

### 1.3 Business Context
- **Core Value:** Delivers a lightweight, high-performance, single-player implementation of a classic abstract strategy game.
- **Architecture Simplicity:** Eliminates database overhead by maintaining match state in frontend memory and stateless backend API payloads.
- **Key Differentiator:** Clean separation between Vite frontend presentation and FastAPI game/AI processing engine.

---

## 2. Problem Statement

### 2.1 User Problem
- Players want a fast, zero-friction single-player game against a smart AI opponent without registration or database setup.
- Focus rules (stack movement, splitting, bottom shedding, reserves) require deterministic backend validation to prevent illegal moves.

### 2.2 Business Problem
- Provide an engaging, performant web application with a FastAPI + Vite stack that adheres strictly to standard architecture conventions.

### 2.3 Success Metrics
- Fast AI response time (< 300ms per AI turn).
- Zero database dependencies (100% stateless API execution).
- 100% compliance with Sid Sackson's official 2-player Focus rules.

---

## 3. Scope

### 3.1 In Scope
- **Architecture:**
  - **Frontend:** Vite + React/TypeScript (UI, board rendering, stack layering, move animations, reserve tray).
  - **Backend:** FastAPI / Python 3.12 (Game engine logic, legal move generation, AI Minimax agent, API endpoints).
- **Game Mode:**
  - **Player vs. AI Only (2-Player setup: Red vs. Green).**
  - AI difficulty levels: Easy (Random/Heuristic), Medium (Tactical Heuristic), Hard (Minimax with Alpha-Beta Pruning).
- **Board Layout:**
  - 8x8 grid with 3 squares removed from each of the 4 corners (52 total active squares).
- **Stacking & Movement Mechanics:**
  - Stacks up to 5 pieces maximum height.
  - Split-stack movement: selecting $K$ checkers from top of stack of height $H$ ($1 \le K \le H \le 5$) and moving exactly $K$ orthogonally valid spaces.
  - Top piece color determines stack control (Human = Red, AI = Green).
- **Capture & Reserve Engine:**
  - Bottom shedding when stack height exceeds 5 after a move.
  - Opponent checkers shed -> permanently captured.
  - Own checkers shed -> added to player's Reserve count.
  - Reserve piece deployment: spend turn to drop 1 reserve piece onto any board tile (empty or occupied).

### 3.2 Out of Scope
- Databases or persistent storage engines (No PostgreSQL, No MongoDB, No SQLite).
- Multiplayer (Human vs Human local or online WebSocket multiplayer is explicitly excluded).
- User authentication, login, or user accounts.

### 3.3 Assumptions
- Frontend runs via Vite dev server (`npm run dev`).
- Backend runs via FastAPI / Uvicorn server (`uvicorn app.main:app --reload`).

---

## 4. Users and Roles

### 4.1 Primary Users
- Solo players seeking a quick, challenging strategy game against an AI opponent.

### 4.2 Roles and Permissions
- **Human Player (Red):** Makes moves or drops reserve pieces on their turn via Vite UI.
- **AI Opponent (Green):** Computes and returns next move via FastAPI endpoint.

---

## 5. Functional Requirements

1. **New Game Initialization:**
   - The system shall initialize the 52-square Focus board with the official 2-player setup (18 Red checkers for Human, 18 Green checkers for AI).
   - FastAPI `/api/game/new` shall return the starting board state matrix, turn indicator, and initial reserves/captures counters.

2. **Move Validation & Execution:**
   - FastAPI `/api/game/move` shall accept current board state + human move payload (source tile, split height $K$, destination tile OR reserve placement).
   - The backend shall validate move legality according to Focus rules.
   - If valid, backend shall execute movement, process bottom-shedding (reserves & captures), update game state, and return the updated board state.

3. **AI Turn Generation:**
   - FastAPI `/api/game/ai-move` shall accept current board state and AI difficulty level.
   - The backend AI module shall execute Minimax with Alpha-Beta pruning to evaluate optimal moves.
   - Backend shall return the AI's selected move, updated board state, and win/loss status.

4. **Merging & Shedding (5-Piece Limit):**
   - Merging stacks beyond height 5 automatically sheds bottom checkers:
     - Active player's own color shed -> increment Active Player Reserves.
     - Opponent's color shed -> increment Active Player Captures.

5. **Win / Loss Detection:**
   - A player loses when they have 0 stacks topped by their color AND 0 reserve pieces remaining.
   - Backend shall evaluate win condition after every move and return `winner: "HUMAN" | "AI" | null`.

---

## 6. AI / Model Requirements

### 6.1 AI Strategy Engine (FastAPI Backend)
- **Algorithm:** Minimax with Alpha-Beta Pruning.
- **Evaluation Heuristics:**
  - Board Dominance: Count of stacks controlled by AI vs. Human.
  - Stack Depth & Safety: Controlling tall stacks vs. vulnerable single checkers.
  - Reserve & Capture Count: Available reserve pieces and permanent captures.
- **Performance:** Response time must remain under 300ms for seamless user experience.

---

## 7. Data Requirements

### 7.1 Data Architecture (No DB)
- **State Transfer:** All match state is passed as JSON request/response payloads between the Vite frontend and FastAPI backend.
- **Session State:** Frontend holds active match state in React component state / LocalStorage (optional for refresh survival).

---

## 8. Integration Requirements

### 8.1 API Endpoints (FastAPI)
- `POST /api/game/new` -> Returns initialized 52-tile board layout.
- `POST /api/game/valid-moves` -> Returns valid destinations for a selected stack & split height.
- `POST /api/game/move` -> Executes human move and updates board state.
- `POST /api/game/ai-move` -> Computes and executes AI move, returning updated state.

---

## 9. Workflow / User Journey

1. **Start Game:** User opens Vite app, selects AI difficulty (Easy / Medium / Hard), and clicks **"Start New Game"**.
2. **Human Move:**
   - User clicks a Red-topped stack on the board.
   - UI shows height selection slider ($1..K$).
   - Vite queries `/api/game/valid-moves` or highlights valid tiles $K$ steps away.
   - User selects target tile (or selects Reserve piece and clicks a tile).
   - Frontend calls `POST /api/game/move`.
3. **AI Move:**
   - Upon successful Human move, frontend automatically triggers `POST /api/game/ai-move`.
   - FastAPI computes AI's best move, updates board/reserves, and returns new state.
   - Vite UI animates AI's move.
4. **Game End:**
   - When either player runs out of moves/reserves, winner modal is displayed with "Play Again" option.

---

## 10. Acceptance Criteria

- [ ] Tech stack uses **FastAPI** for backend and **Vite** for frontend.
- [ ] No database or external storage service is used.
- [ ] Game mode is strictly **Player vs AI**.
- [ ] Backend accurately validates stack movement, splitting ($1..K$), orthogonal pathing, bottom-shedding, and reserve placement.
- [ ] AI computes and executes valid counter-moves cleanly.
- [ ] Game over detection correctly identifies when Human or AI has no remaining legal moves.

---

## 11. Implementation Phases

### Phase 1: FastAPI Backend Game Engine
- Setup FastAPI project structure.
- Implement board model, move validation logic, bottom-shedding engine, and game over checks.
- Implement Minimax AI algorithm with difficulty levels.
- Write pytest unit tests for all board mechanics and rule edge cases.

### Phase 2: Vite Frontend & API Integration
- Setup Vite React/TypeScript app.
- Build 52-square board UI with visual checker stacking and reserve tray.
- Connect frontend to FastAPI endpoints (`/api/game/new`, `/api/game/move`, `/api/game/ai-move`).
- Add move indicators, animations, and game over victory screen.
