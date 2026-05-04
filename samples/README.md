# Sample LogiBox circuits

- These samples are pre-saved in the release (zip folder).
You can change or delete them freely.
The samples exist to represent what can be done using LogiBox.


- When you want to retrieve them:
Drop any of these samples into your `saves/` folder which is
in the same directory as LogiBox.exe, then inside LogiBox run
the specified load command for the sample to load it.


## Sample List:

### alu16.txt | 16-bit ALU

- Load command: `load alu16`

A complete arithmetic-logic unit with eight operations, four status
flags, and a 3-bit opcode selector. 209 variables.

**Operations** (selected by `S2 S1 S0`):

| Selector | Operation |
|----------|-----------|
| 000 | ADD (A + B) |
| 001 | SUB (A − B, two's complement) |
| 010 | AND |
| 011 | OR |
| 100 | XOR |
| 101 | NOT A |
| 110 | SHL A (shift left by 1) |
| 111 | SHR A (shift right by 1) |

**Inputs:** `A0..A15`, `B0..B15`, `S0..S2` (set with `set A = ...`,
`set B = ...`, `set S = ...`).

**Outputs:** `out0..out15` (read with `show out`), plus the
flags `zero`, `negative`, `carry_out`, `overflow`.

Example:

    load alu16
    set A = 0000010011010010    # 1234
    set B = 0001011000101110    # 5678
    set S = 000                 # ADD
    show out                    # -> 6912 (1234 + 5678)

### digit7seg.txt | 4-bit BCD to 7-segment decoder

- Load command: `load digit7seg`

Converts a 4-bit number (0-9) into seven outputs that drive a
calculator-style digit display. 21 variables.

**Inputs:** `D`, `C`, `B`, `A` (4-bit binary, D = MSB)

**Outputs:** `seg_a` through `seg_g` (1 = segment lit)

Segment layout:

           aaa
          f   b
          f   b
           ggg
          e   c
          e   c
           ddd

Example:

    load digit7seg
    D = 0
    C = 1
    B = 0
    A = 1                       # binary 0101 = digit 5
    seg_a                       # -> 1
    seg_b                       # -> 0
    seg_c                       # -> 1
    seg_d                       # -> 1
    seg_e                       # -> 0
    seg_f                       # -> 1
    seg_g                       # -> 1

Inputs above 9 (binary 1010 to 1111) produce all-zero output;
this is a BCD decoder and ignores invalid inputs.

## Reading the source

Every save file is plain text. Open one and read it — the engine
language is exactly what you'd type into LogiBox interactively, so
the file is both data and documentation. Comments after `#` are
preserved through save and load.

<sub>*More samples will be added in future*</sub>
