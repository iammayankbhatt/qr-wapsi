import { useParams } from 'react-router-dom'
import PagePlaceholder from '../components/PagePlaceholder'

export default function MerchantJourney() {
  const { id } = useParams()
  return <PagePlaceholder title="Merchant journey" detail={`Merchant: ${id}`} />
}
