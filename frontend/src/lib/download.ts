export function downloadBlob(url: string, filename: string, token?: string): void {
  fetch(url, token ? { headers: { Authorization: `Bearer ${token}` } } : {})
    .then(r => r.blob())
    .then(blob => {
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = filename
      a.click()
      setTimeout(() => URL.revokeObjectURL(a.href), 100)
    })
}
