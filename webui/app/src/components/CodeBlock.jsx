import './CodeBlock.css'

export default function CodeBlock({ code, language = 'text' }) {
  return (
    <pre className="code-block">
      <code className={`language-${language}`}>{code}</code>
    </pre>
  )
}
