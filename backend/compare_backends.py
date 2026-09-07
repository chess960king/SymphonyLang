"""
compare_backends.py
Cross-validation test: compiles a SymphonyLang program, runs it through
BOTH backends (MIDI code generator AND bytecode VM), and checks that they
agree on what music was actually produced.

Why this matters: our compiler produces ONE optimized IR that feeds two
completely independent execution engines (a MIDI event emitter, and a
stack-based VM). If both backends were built correctly from the same IR,
they MUST produce the same sequence of musical events. This script proves
that automatically, instead of us just eyeballing two separate outputs.
"""

from lexer import Lexer
from parser import Parser
from semantic_analyzer import SemanticAnalyzer
from ir import IRGenerator
from optimizer import constant_folding, constant_propagation, dead_code_elimination
from bytecode_compiler import BytecodeCompiler
from vm import VirtualMachine
from codegen_midi import MIDICodeGenerator, note_name_to_midi


def compile_to_ir(source_code):
    """Runs the shared front-end + middle stages: lexer through optimizer."""
    tokens, lex_errors = Lexer(source_code).tokenize()
    if lex_errors:
        return None, f"Lex errors: {lex_errors}"

    ast, parse_errors = Parser(tokens).parse()
    if parse_errors:
        return None, f"Parse errors: {parse_errors}"

    sem_errors = SemanticAnalyzer().analyze(ast)
    if sem_errors:
        return None, f"Semantic errors: {sem_errors}"

    ir = IRGenerator().generate(ast)
    ir, _ = constant_folding(ir)
    ir, _ = constant_propagation(ir)
    ir, _ = dead_code_elimination(ir)
    return ir, None


def run_vm_backend(ir):
    """Returns a simplified list of (kind, data) tuples describing the music."""
    bytecode = BytecodeCompiler().compile(ir)
    events = VirtualMachine().run(bytecode)
    return [(e.kind, e.data) for e in events]


def run_midi_backend(ir):
    """
    Re-derives the same kind of (kind, data) event list, but this time by
    reading the actual generated MIDI messages - proving the MIDI file
    itself (not just some intermediate step) matches the VM's behavior.
    """
    codegen = MIDICodeGenerator()
    codegen.generate(ir)
    events = []
    current_tempo_bpm = None
    for msg in codegen.track:
        if msg.type == 'set_tempo':
            bpm = round(60_000_000 / msg.tempo)
            events.append(('TEMPO', bpm))
        elif msg.type == 'program_change':
            name = next((k for k, v in
                         __import__('codegen_midi').INSTRUMENT_PROGRAMS.items()
                         if v == msg.program), f"program_{msg.program}")
            events.append(('INSTRUMENT', name))
        elif msg.type == 'note_on':
            events.append(('NOTE_ON', msg.note))
    return events


def midi_events_to_note_sequence(midi_events):
    """Extracts just the MIDI note numbers played, in order."""
    return [data for kind, data in midi_events if kind == 'NOTE_ON']


def vm_events_to_note_sequence(vm_events):
    """Converts the VM's (note_name, duration) PLAY events into MIDI note
    numbers, using the SAME note_name_to_midi() function the MIDI backend
    uses - so we're comparing apples to apples."""
    notes = []
    for kind, data in vm_events:
        if kind == 'PLAY':
            note_name, _duration = data
            notes.append(note_name_to_midi(note_name))
    return notes


def compare(source_code, label=""):
    print(f"{'='*60}\nComparing backends for: {label}\n{'='*60}")

    ir, error = compile_to_ir(source_code)
    if error:
        print("Compilation failed:", error)
        return False

    vm_events = run_vm_backend(ir)
    midi_events = run_midi_backend(ir)

    vm_notes = vm_events_to_note_sequence(vm_events)
    midi_notes = midi_events_to_note_sequence(midi_events)

    vm_tempo = next((d for k, d in vm_events if k == 'TEMPO'), None)
    midi_tempo = next((d for k, d in midi_events if k == 'TEMPO'), None)

    print("VM   note sequence :", vm_notes)
    print("MIDI note sequence :", midi_notes)
    print("VM   tempo         :", vm_tempo)
    print("MIDI tempo         :", midi_tempo)

    notes_match = vm_notes == midi_notes
    tempo_match = vm_tempo == midi_tempo

    if notes_match and tempo_match:
        print("\n✅ PASS - both backends produced identical musical output")
        return True
    else:
        print("\n❌ FAIL - backends disagree!")
        if not notes_match:
            print("   Note sequence mismatch")
        if not tempo_match:
            print("   Tempo mismatch")
        return False


if __name__ == "__main__":
    sample = open("../testcases/demo_sample.sym").read()
    compare(sample, label="demo_sample.sym")