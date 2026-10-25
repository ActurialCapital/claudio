// ```transcript fences become <Transcript text="..." />, so claudio's terminal output keeps its exact spacing
// (MDX strips leading spaces from lines written inside a JSX expression).
type Node = { type: string; lang?: string | null; value?: string; children?: Node[] };

export function remarkTranscript() {
  return (tree: Node) => {
    const walk = (node: Node) => {
      node.children?.forEach((child, i, siblings) => {
        if (child.type === 'code' && child.lang === 'transcript') {
          siblings[i] = {
            type: 'mdxJsxFlowElement',
            name: 'Transcript',
            attributes: [{ type: 'mdxJsxAttribute', name: 'text', value: child.value ?? '' }],
            children: [],
          } as Node;
        } else walk(child);
      });
    };
    walk(tree);
  };
}
