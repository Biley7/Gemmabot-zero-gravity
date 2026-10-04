import time
import streamlit as st
from dotenv import load_dotenv
from gemmabot.simulator import new_world, render, step, reached_goal
from gemmabot.planner import ask_api, ask_ollama, parse_plan

load_dotenv()
st.set_page_config(page_title="Gemma Robot Brain", page_icon="🤖")
st.title("🤖 Gemma Robot Brain")
st.caption("Type an instruction. Gemma plans the moves, the virtual robot runs them.")

if "world" not in st.session_state:
    st.session_state.world = new_world()
    st.session_state.log = []
    st.session_state.cache = {}   # same instruction + same state = no new API call

backend = st.sidebar.radio(
    "Brain", ["Gemini API (Gemma)", "Local Ollama (Gemma)", "Auto: API, then local"])
if st.sidebar.button("Reset world"):
    st.session_state.world = new_world()
    st.session_state.log = []

board = st.empty()

def draw():
    html = "<div style='font-size:30px;line-height:1.25'>" + "<br>".join(
        render(st.session_state.world)) + "</div>"
    board.markdown(html, unsafe_allow_html=True)

draw()
instruction = st.text_input("Instruction", "Go to the goal around the walls")

if st.button("Run") and instruction:
    world = st.session_state.world
    key = (instruction, str(world))
    reply = st.session_state.cache.get(key)
    if reply is None:
        try:
            if backend.startswith("Gemini"):
                reply = ask_api(instruction, world)
            elif backend.startswith("Local"):
                reply = ask_ollama(instruction, world)
            else:
                try:
                    reply = ask_api(instruction, world)
                except Exception as e:
                    st.warning(f"API failed ({type(e).__name__}); using local Ollama.")
                    reply = ask_ollama(instruction, world)
            st.session_state.cache[key] = reply
        except Exception as e:
            st.error(f"Model call failed: {e}")
            reply = None
    if reply:
        try:
            thought, actions = parse_plan(reply)
            st.info(f"🧠 {thought}")
            for a in actions:
                msg = step(world, a)
                st.session_state.log.append(f"{a} -> {msg}")
                draw()
                time.sleep(0.5)
            if reached_goal(world):
                st.success("🎯 Goal reached!")
        except Exception as e:
            st.error(f"Could not read the model's plan: {e}")
            st.code(reply)

with st.expander("Action log"):
    for line in st.session_state.log:
        st.text(line)
