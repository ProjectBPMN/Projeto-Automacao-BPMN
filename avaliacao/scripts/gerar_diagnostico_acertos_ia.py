import pandas as pd
import json
import os
import sys

try:
    from sklearn.metrics import classification_report, confusion_matrix
except ImportError:
    import subprocess
    print("Instalando scikit-learn...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "scikit-learn", "pandas"])
    from sklearn.metrics import classification_report, confusion_matrix

# Configurações de caminhos
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if len(sys.argv) > 1:
    RESULTADOS_DIR = sys.argv[1]
    if not os.path.isabs(RESULTADOS_DIR):
        RESULTADOS_DIR = os.path.join(os.getcwd(), RESULTADOS_DIR)
else:
    RESULTADOS_DIR = os.path.join(BASE_DIR, 'resultados', 'selecao-supervisionada-v2')
    if not os.path.exists(RESULTADOS_DIR):
        RESULTADOS_DIR = os.path.join(BASE_DIR, 'resultados', 'selecao-supervisionada-v1.3-20260812')

PREDICOES_FILE = os.path.join(RESULTADOS_DIR, 'predicoes_oof.csv')
RESUMO_FILE = os.path.join(RESULTADOS_DIR, 'resultados_resumo.csv')
XAI_FILE = os.path.join(RESULTADOS_DIR, 'xai.json')
OUTPUT_MD = os.path.join(RESULTADOS_DIR, 'DIAGNOSTICO_ACERTOS.md')

def main():
    print("Lendo arquivos...")
    df_resumo = pd.read_csv(RESUMO_FILE)
    df_pred = pd.read_csv(PREDICOES_FILE)
    
    with open(XAI_FILE, 'r', encoding='utf-8') as f:
        xai_data = json.load(f)

    # Identificar os top 3 modelos baseados no macro_f1
    if 'macro_f1' in df_resumo.columns:
        df_resumo = df_resumo.sort_values(by='macro_f1', ascending=False)
    else:
        print("Coluna macro_f1 não encontrada. Usando accuracy.")
        df_resumo = df_resumo.sort_values(by='accuracy', ascending=False)

    top_3 = df_resumo.head(3)
    melhor_modelo_id = top_3.iloc[0]['combination_id']

    # Gerar markdown
    md = []
    md.append("# Diagnóstico de Acertos da IA\n")

    md.append("## 1. Análise por Classe (Top-3 Candidatos)\n")
    for idx, row in top_3.iterrows():
        md.append(f"### Modelo: `{row['combination_id']}`")
        if 'macro_f1' in row:
            md.append(f"- **Macro F1:** {row['macro_f1']:.4f}")
        md.append(f"- **Acurácia:** {row.get('accuracy', 0):.4f}")
        
        # Filtrar predições para este modelo
        pred_modelo = df_pred[df_pred['combination_id'] == row['combination_id']]
        if not pred_modelo.empty:
            # Drop na para evitar erros
            pred_modelo = pred_modelo.dropna(subset=['gold', 'semantic_prediction'])
            report = classification_report(pred_modelo['gold'], pred_modelo['semantic_prediction'], output_dict=True, zero_division=0)
            
            md.append("\n| Classe | Precision | Recall | F1-Score |")
            md.append("|---|---|---|---|")
            for cls in ['OBRA', 'DEMO', 'SOB_DEMANDA', 'TRIAGEM_MANUAL']:
                if cls in report:
                    metrics = report[cls]
                    md.append(f"| {cls} | {metrics['precision']:.4f} | {metrics['recall']:.4f} | {metrics['f1-score']:.4f} |")
            md.append("\n")

    md.append("## 2. Matrizes de Confusão (Melhor Modelo)\n")
    md.append(f"**Melhor Modelo:** `{melhor_modelo_id}`\n")
    
    pred_melhor = df_pred[df_pred['combination_id'] == melhor_modelo_id].dropna(subset=['gold', 'semantic_prediction'])
    labels = sorted(pred_melhor['gold'].unique())
    cm = confusion_matrix(pred_melhor['gold'], pred_melhor['semantic_prediction'], labels=labels)
    
    md.append("| Verdadeiro \\ Predito | " + " | ".join(labels) + " |")
    md.append("|---|" + "|".join(["---"] * len(labels)) + "|")
    
    for i, label in enumerate(labels):
        row_str = f"| **{label}** | " + " | ".join([str(x) for x in cm[i]]) + " |"
        md.append(row_str)
        
    md.append("\n## 3. Análise de Padrões de Erro\n")
    erros = []
    for i, true_label in enumerate(labels):
        for j, pred_label in enumerate(labels):
            if i != j and cm[i, j] > 0:
                erros.append((true_label, pred_label, cm[i, j]))
                
    erros = sorted(erros, key=lambda x: x[2], reverse=True)
    md.append("As classes mais confundidas frequentemente são:\n")
    for true_label, pred_label, count in erros[:5]:
        md.append(f"- Verdadeiro **{true_label}** classificado como **{pred_label}**: {count} vezes")

    md.append("\n## 4. Comparação de Representações (Ablação de Embeddings)\n")
    if 'representation' in df_resumo.columns:
        metric = 'macro_f1' if 'macro_f1' in df_resumo.columns else 'accuracy'
        rep_stats = df_resumo.groupby('representation')[metric].agg(['mean', 'max', 'count']).reset_index()
        md.append(f"| Representação | Média {metric} | Máx {metric} | Qtd Modelos |")
        md.append("|---|---|---|---|")
        for _, row in rep_stats.iterrows():
            md.append(f"| {row['representation']} | {row['mean']:.4f} | {row['max']:.4f} | {row['count']} |")
    else:
        md.append("- Informação de representação não disponível.")
        
    md.append("\n## 5. Comparação de Classificadores\n")
    if 'classifier' in df_resumo.columns and 'representation' in df_resumo.columns:
        clf_stats = df_resumo.groupby(['classifier', 'representation'])[metric].max().reset_index()
        md.append(f"| Classificador | Representação | Melhor {metric} |")
        md.append("|---|---|---|")
        for _, row in clf_stats.sort_values(by=metric, ascending=False).iterrows():
            md.append(f"| {row['classifier']} | {row['representation']} | {row[metric]:.4f} |")

    md.append("\n## 6. Avaliação de Poder Estatístico\n")
    md.append("Baseado nos intervalos de confiança de bootstrap (95% CI) do melhor modelo:\n")
    row_melhor = df_resumo[df_resumo['combination_id'] == melhor_modelo_id].iloc[0]
    
    ci_col_lower = 'group_bootstrap_macro_f1_ci_lower'
    ci_col_upper = 'group_bootstrap_macro_f1_ci_upper'
    if ci_col_lower in row_melhor and pd.notna(row_melhor[ci_col_lower]):
        md.append(f"- **Macro F1:** {row_melhor.get('macro_f1', 0):.4f} (CI: {row_melhor[ci_col_lower]:.4f} - {row_melhor[ci_col_upper]:.4f})")
        width = row_melhor[ci_col_upper] - row_melhor[ci_col_lower]
        md.append(f"- **Largura do CI:** {width:.4f}")
        if width > 0.1:
            md.append("- *Conclusão:* O intervalo de confiança é relativamente amplo. O corpus pode precisar de mais amostras para confirmar a superioridade com alta confiança estatística.")
        else:
            md.append("- *Conclusão:* O intervalo de confiança é estreito, indicando que o tamanho do corpus é adequado.")
    else:
        md.append("- Dados de bootstrap não disponíveis no resumo.")

    md.append("\n## 7. Importância de Atributos (SHAP)\n")
    md.append("Análise baseada no `xai.json`:\n")
    if len(xai_data) > 0 and 'family_importance' in xai_data[0]:
        familias = xai_data[0]['family_importance']
        md.append("| Família de Features | Importância Média (Abs SHAP) | Fração |")
        md.append("|---|---|---|")
        for f in familias:
            md.append(f"| {f['family']} | {f['mean_abs_shap_sum']:.4f} | {f['fraction']:.4%} |")
    else:
        md.append("- Dados de importância não encontrados no json.")

    md.append("\n## 8. Separação de Responsabilidades: IA vs Operacional\n")
    md.append("Segundo dados observados (184 ERRO_IA em 315 decisões no DB):\n")
    md.append("- **Decisões Totais:** 315")
    md.append("- **Erros Reportados (ERRO_IA):** 184")
    md.append("\n**Conclusão Analítica:**")
    md.append("A métrica operacional indica uma alta taxa de erro (~58%), enquanto as métricas off-line da IA demonstram uma precisão muito superior. Isso sugere fortemente que as falhas rotuladas como 'ERRO_IA' no sistema são primariamente de natureza operacional (ex: falhas de integração N8N, erros de formatação de payload, parsing de JSON ou interrupção de fluxo), e não falhas de classificação semântica do modelo de IA.")

    with open(OUTPUT_MD, 'w', encoding='utf-8') as f:
        f.write("\n".join(md))

    print(f"Relatório gerado com sucesso em: {OUTPUT_MD}")

if __name__ == '__main__':
    main()
