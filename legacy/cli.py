"""Human-facing I/O and approval boundary, separate from model decisions."""
import argparse
import difflib
import json
import sys
from terminal_safety import terminal_text

import tools
from patching import PatchError, PatchReceipt, apply_patch, rollback
from patch_journal import save_receipt, load_receipt
from patch_workflow import restore_preview
from protocol import ModelGateway
from repository_source import prepare_repository, RepositorySourceError


def confirm(token, *, input_fn=None):
    if not sys.stdin.isatty():
        raise PatchError('Dosya yazmak için etkileşimli terminal ve insan onayı gerekir.')
    answer = (input_fn or input)(f'Onaylamak için {token} yaz; vazgeçmek için Enter: ')
    if answer != token:
        raise PatchError('Onay verilmedi; dosya değiştirilmedi.')
    return answer


def main(argv=None, *, runner=None):
    from agent import run_agent, MODEL_NAME, MODEL_THINK, FAST_MODEL_NAME, _cli_exit_code
    parser = argparse.ArgumentParser(description='Local repository research, diagnosis and approved small patches')
    parser.add_argument('issue', nargs='?', help='Araştırılacak soru veya değişiklik isteği')
    parser.add_argument('--repo', default=str(tools.PROJECT_ROOT), help='Yerel klasör veya public GitHub HTTPS adresi')
    parser.add_argument('--model', default=MODEL_NAME)
    parser.add_argument('--json', action='store_true')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--summary', action='store_true', help='Sınırlı kaynak okumasıyla repository özeti')
    mode.add_argument('--plan', action='store_true', help='Diagnosis sonrası yalnız değişiklik planı')
    mode.add_argument('--patch', action='store_true', help='Plan ve küçük diff üret; dosya yazma')
    mode.add_argument('--apply', action='store_true', help='Diff üret ve insan onayından sonra uygula')
    mode.add_argument('--rollback', metavar='RECEIPT', help='Kaydedilmiş patch için onaylı geri alma')
    args = parser.parse_args(argv)
    if (args.apply or args.rollback) and args.json:
        parser.error('--json ile etkileşimli yazma birlikte kullanılamaz; --patch --json kullan.')
    if not args.issue and not (args.summary or args.rollback):
        parser.error('Bir soru ver veya --summary kullan.')
    previous_root = tools.PROJECT_ROOT
    try:
        if (args.apply or args.rollback) and not sys.stdin.isatty():
            raise PatchError('Yazma/geri alma için etkileşimli terminal gerekir; önizleme için --patch kullan.')
        if args.rollback:
            receipt = load_receipt(args.rollback)
            preview = receipt.preview
            print(f'[GERİ ALMA] {terminal_text(preview.repository)}/{terminal_text(preview.file)}')
            diff = ''.join(difflib.unified_diff(
                preview.replacement.decode().splitlines(True), preview.original.decode().splitlines(True),
                fromfile='patched/' + preview.file, tofile='original/' + preview.file))
            print(terminal_text(diff))
            rollback(receipt, confirm(receipt.rollback_id))
            print('[GERİ ALINDI] Yalnız bu patch geri alındı.')
            return 0
        selected = prepare_repository(args.repo)
        tools.PROJECT_ROOT = selected.path
        if not args.json:
            print(f'[REPOSITORY] {terminal_text(selected.path)}')
            if selected.commit:
                print(f'[COMMIT] {selected.commit}\n[NOT] İndirilen proje kodu veya testleri çalıştırılmayacak.')
        gateway = ModelGateway(args.model, think=MODEL_THINK, fast_model_name=FAST_MODEL_NAME)
        if args.summary:
            from repository_summary import summarize_repository
            result = summarize_repository(args.issue, gateway,
                progress=None if args.json else lambda text: print(terminal_text(text)))
            result['repository'] = selected.metadata()
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print('[ÖZET]')
                for finding in result['findings']:
                    print(terminal_text(finding['answer']))
                    for source in finding['evidence']:
                        print(terminal_text(f"  {source['file']}:{source['start_line']}-{source['end_line']}"))
                for limitation in result['limitations']:
                    print('[SINIR] ' + terminal_text(limitation))
                if result['reason']:
                    print('[NEDEN] ' + terminal_text(result['reason']))
                print('[NOT] Kaynak konumları kontrol edildi; model özeti doğruluk garantisi değildir, insan incelemesi gerekir.')
            return _cli_exit_code(result['status'])
        result = (runner or run_agent)(args.issue, gateway=gateway, json_output=args.json,
            repository_info=selected.metadata(), plan_changes=args.plan,
            patch_changes=args.patch or args.apply)
        if result.patch_preview is not None and not args.json:
            preview = restore_preview(result.patch_preview)
            print('\n[PATCH ÖNİZLEME — HENÜZ UYGULANMADI]')
            print(terminal_text(preview.diff))
            print('[KONTROL] Yol, kanıt sürümü, küçük diff ve Python sözdizimi kontrol edildi. Davranış test edilmedi.')
            if args.apply:
                approval = confirm(preview.approval_id)
                # Recovery data is persisted BEFORE writing. If saving fails,
                # application must not leave a file with no rollback snapshot.
                import hashlib
                rollback_id = 'ROLLBACK-' + hashlib.sha256(preview.approval_id.encode('ascii')).hexdigest()[:24]
                receipt_path = save_receipt(PatchReceipt(preview, rollback_id))
                print(f'[GERİ ALMA KAYDI] {receipt_path}')
                apply_patch(preview, approval)
                print('[UYGULANDI]')
                print(terminal_text(preview.diff))
                print(f'Geri almak için: python agent.py --rollback "{receipt_path}"')
                print('[NOT] Kayıt geçici dizindedir; kalıcı saklamak istersen güvenli bir yere kopyala.')
        return _cli_exit_code(result.status)
    except (RepositorySourceError, PatchError, ValueError, OSError) as error:
        if args.json:
            print(json.dumps({'status': 'stopped', 'reason': str(error)}, ensure_ascii=False))
        else:
            print('[DURDURULDU] ' + terminal_text(error), file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print('\nİptal edildi.', file=sys.stderr)
        return 130
    finally:
        tools.PROJECT_ROOT = previous_root
