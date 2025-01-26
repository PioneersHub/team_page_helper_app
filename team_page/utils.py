def obfuscate_name(text):
   def mask_name(name):
       return name[0] + '*' * (len(name)-1)

   words = text.split()
   return ' '.join(mask_name(w) if w[0].isupper() else w for w in words)
