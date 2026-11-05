; Entirely authored fixture. No original game instructions or identity inputs.
; Keep the observer's selected RVA and 177-byte window without changing it.
.code
ORG 0C2F7C0h
PUBLIC Fixture
Fixture PROC
    DB 16 DUP (090h)
    lea rax, [rcx+rdx]
    ret
    DB (0B1h-21) DUP (090h)
Fixture ENDP
.data
relocation_anchor DQ OFFSET Fixture
END
